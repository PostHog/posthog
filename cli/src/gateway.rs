//! `posthog-cli gateway token`: a short-lived AI gateway developer mode token for PostHog staff.
//!
//! The CLI never holds a PostHog credential. It opens the browser on PostHog's developer mode
//! settings with a PKCE challenge and a loopback port; the signed-in staff member approves, the
//! browser hands a one-time code to `127.0.0.1:<port>`, and the CLI exchanges the code plus its
//! verifier for a `phe_` token pinned to that staff member.

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::time::{Duration, Instant};
use tracing::info;

const DEFAULT_HOST: &str = "https://us.posthog.com";
const SETTINGS_PATH: &str = "/settings/user-ai-gateway-dev-mode";
const EXCHANGE_PATH: &str = "/api/ai_gateway/dev_tokens/cli_exchange/";
const APPROVAL_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Serialize)]
struct ExchangeRequest<'a> {
    code: &'a str,
    code_verifier: &'a str,
}

#[derive(Deserialize, Serialize)]
pub struct MintedToken {
    pub token: String,
    pub expires_at: String,
    pub cap_usd: String,
    pub gateway_url: String,
}

#[derive(Deserialize)]
struct Refusal {
    detail: Option<String>,
}

pub fn token(host: Option<String>, json: bool) -> Result<()> {
    let host = host
        .unwrap_or_else(|| DEFAULT_HOST.to_string())
        .trim_end_matches('/')
        .to_string();
    let verifier = random_hex(64);
    let state = random_hex(32);
    let challenge = s256(&verifier);

    let listener = TcpListener::bind("127.0.0.1:0").context("Failed to open a loopback port")?;
    let port = listener.local_addr()?.port();
    let url = format!(
        "{host}{SETTINGS_PATH}?cli_challenge={challenge}&cli_port={port}&cli_state={state}"
    );

    eprintln!("Approve the request in your browser. If no browser opened, go to:\n\n  {url}\n");
    if let Err(e) = open::that(&url) {
        info!("could not open a browser: {e}");
    }

    let code = wait_for_code(&listener, &state)?;
    let minted = exchange(&host, &code, &verifier)?;

    if json {
        println!("{}", serde_json::to_string(&minted)?);
    } else {
        println!("{}", minted.token);
        eprintln!(
            "\nThe token expires at {} and can spend up to ${}.",
            minted.expires_at, minted.cap_usd
        );
    }
    Ok(())
}

fn wait_for_code(listener: &TcpListener, state: &str) -> Result<String> {
    listener.set_nonblocking(true)?;
    let deadline = Instant::now() + APPROVAL_TIMEOUT;
    loop {
        match listener.accept() {
            Ok((stream, _)) => {
                if let Some(code) = handle_callback(stream, state)? {
                    return Ok(code);
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                if Instant::now() >= deadline {
                    bail!("No approval after 5 minutes. Run the command again.");
                }
                std::thread::sleep(Duration::from_millis(200));
            }
            Err(e) => return Err(e).context("Failed to accept the browser callback"),
        }
    }
}

/// Answers one loopback request. Returns the code only for a `/callback` whose state matches.
fn handle_callback(mut stream: TcpStream, state: &str) -> Result<Option<String>> {
    stream.set_nonblocking(false)?;
    stream.set_read_timeout(Some(Duration::from_secs(5)))?;
    let mut request_line = String::new();
    BufReader::new(&stream).read_line(&mut request_line)?;
    let target = request_line.split_whitespace().nth(1).unwrap_or("");
    let code = parse_callback(target, state);
    let body = if code.is_some() {
        "Approved. You can close this tab and return to your terminal."
    } else {
        "This request doesn't match the posthog-cli command you ran."
    };
    let status = if code.is_some() {
        "200 OK"
    } else {
        "400 Bad Request"
    };
    write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    )?;
    Ok(code)
}

fn parse_callback(target: &str, state: &str) -> Option<String> {
    let url = url::Url::parse(&format!("http://127.0.0.1{target}")).ok()?;
    if url.path() != "/callback" {
        return None;
    }
    let mut code = None;
    let mut state_ok = false;
    for (key, value) in url.query_pairs() {
        match key.as_ref() {
            "code" => code = Some(value.into_owned()),
            "state" => state_ok = value == state,
            _ => {}
        }
    }
    if state_ok {
        code.filter(|c| !c.is_empty())
    } else {
        None
    }
}

fn exchange(host: &str, code: &str, verifier: &str) -> Result<MintedToken> {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()?;
    let response = client
        .post(format!("{host}{EXCHANGE_PATH}"))
        .json(&ExchangeRequest {
            code,
            code_verifier: verifier,
        })
        .send()
        .context("Failed to reach PostHog")?;
    let status = response.status();
    if !status.is_success() {
        let detail = response
            .json::<Refusal>()
            .ok()
            .and_then(|r| r.detail)
            .unwrap_or_else(|| format!("HTTP {status}"));
        bail!("Couldn't get a token: {detail}");
    }
    response
        .json::<MintedToken>()
        .context("PostHog returned an unexpected response")
}

/// `len` lowercase hex characters from the OS random source (via UUIDv4), within the PKCE verifier alphabet.
fn random_hex(len: usize) -> String {
    let mut out = String::with_capacity(len + 32);
    while out.len() < len {
        out.push_str(&uuid::Uuid::new_v4().simple().to_string());
    }
    out.truncate(len);
    out
}

fn s256(verifier: &str) -> String {
    base64url(&Sha256::digest(verifier.as_bytes()))
}

fn base64url(bytes: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::with_capacity(bytes.len().div_ceil(3) * 4);
    for chunk in bytes.chunks(3) {
        let n = chunk
            .iter()
            .enumerate()
            .fold(0u32, |acc, (i, b)| acc | (u32::from(*b) << (16 - 8 * i)));
        let chars = chunk.len() + 1;
        for i in 0..chars {
            out.push(ALPHABET[((n >> (18 - 6 * i)) & 0x3f) as usize] as char);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    // RFC 7636 appendix B.
    #[test]
    fn s256_matches_the_rfc_vector() {
        assert_eq!(
            s256("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
            "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
        );
    }

    #[test]
    fn verifier_is_long_enough_and_pkce_safe() {
        let verifier = random_hex(64);
        assert_eq!(verifier.len(), 64);
        assert!(verifier.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(verifier, random_hex(64));
    }

    #[test]
    fn listener_skips_a_stray_request_and_returns_the_callback_code() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        let sender = std::thread::spawn(move || {
            for target in ["/favicon.ico", "/callback?code=c0de&state=s1"] {
                let mut stream = TcpStream::connect(addr).unwrap();
                write!(stream, "GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n").unwrap();
                let mut response = String::new();
                std::io::Read::read_to_string(&mut stream, &mut response).unwrap();
            }
        });
        assert_eq!(wait_for_code(&listener, "s1").unwrap(), "c0de");
        sender.join().unwrap();
    }

    #[test]
    fn callback_requires_the_matching_state() {
        assert_eq!(
            parse_callback("/callback?code=abc&state=s1", "s1"),
            Some("abc".to_string())
        );
        assert_eq!(parse_callback("/callback?code=abc&state=s2", "s1"), None);
        assert_eq!(parse_callback("/callback?code=abc", "s1"), None);
        assert_eq!(parse_callback("/other?code=abc&state=s1", "s1"), None);
        assert_eq!(parse_callback("/callback?code=&state=s1", "s1"), None);
    }
}
