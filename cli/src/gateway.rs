//! `posthog-cli gateway token`: a short-lived AI gateway developer mode token for PostHog staff.
//!
//! The CLI never holds a PostHog credential. It opens the browser on PostHog's developer mode
//! settings with a PKCE challenge and a loopback port; the signed-in staff member approves, the
//! browser hands a one-time code to `127.0.0.1:<port>`, and the CLI exchanges the code plus its
//! verifier for a `phe_` token pinned to that staff member.

use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpListener;
use std::time::{Duration, Instant};
use tracing::info;

const DEFAULT_HOST: &str = "https://us.posthog.com";
const SETTINGS_PATH: &str = "/settings/user-ai-gateway-dev-mode";
const EXCHANGE_PATH: &str = "/api/ai_gateway/dev_tokens/cli_exchange/";
const APPROVAL_TIMEOUT: Duration = Duration::from_secs(300);
const CONNECTION_READ_TIMEOUT: Duration = Duration::from_secs(5);
const MAX_REQUEST_LINE_BYTES: u64 = 8 * 1024;

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

    let code = wait_for_code(&listener, &state, APPROVAL_TIMEOUT, CONNECTION_READ_TIMEOUT)?;
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

/// Waits for the browser callback. An error on one connection skips that connection only,
/// so an idle, aborted or malformed connection cannot end the wait.
fn wait_for_code(
    listener: &TcpListener,
    state: &str,
    timeout: Duration,
    read_timeout: Duration,
) -> Result<String> {
    listener.set_nonblocking(true)?;
    let deadline = Instant::now() + timeout;
    loop {
        if Instant::now() >= deadline {
            bail!(
                "No approval after {} seconds. Run the command again.",
                timeout.as_secs()
            );
        }
        match listener.accept() {
            Ok((stream, _)) => {
                if let Err(e) = stream
                    .set_nonblocking(false)
                    .and_then(|()| stream.set_read_timeout(Some(read_timeout)))
                {
                    info!("skipped a loopback connection: {e}");
                    continue;
                }
                if let Some(code) = handle_callback(stream, state) {
                    return Ok(code);
                }
            }
            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                std::thread::sleep(Duration::from_millis(200));
            }
            Err(e) => {
                info!("could not accept a loopback connection: {e}");
                std::thread::sleep(Duration::from_millis(200));
            }
        }
    }
}

/// Answers one loopback request. Returns the code only for a `/callback` whose state matches.
/// The response to the browser is best effort: a failed write does not discard a received code.
fn handle_callback(mut stream: impl Read + Write, state: &str) -> Option<String> {
    let mut request_line = String::new();
    let read =
        BufReader::new((&mut stream).take(MAX_REQUEST_LINE_BYTES)).read_line(&mut request_line);
    if let Err(e) = read {
        info!("skipped a loopback connection: {e}");
        return None;
    }
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
    if let Err(e) = write!(
        stream,
        "HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
        body.len()
    ) {
        info!("could not answer the browser: {e}");
    }
    code
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
    use std::net::TcpStream;

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
        let code = wait_for_code(
            &listener,
            "s1",
            Duration::from_secs(10),
            CONNECTION_READ_TIMEOUT,
        );
        assert_eq!(code.unwrap(), "c0de");
        sender.join().unwrap();
    }

    #[test]
    fn listener_skips_idle_and_malformed_connections() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let addr = listener.local_addr().unwrap();
        // The idle connection is first in the accept queue. It sends nothing, so its read times out.
        let _idle = TcpStream::connect(addr).unwrap();
        let mut malformed = TcpStream::connect(addr).unwrap();
        malformed
            .write_all(b"\xff\xfe /callback HTTP/1.1\r\n\r\n")
            .unwrap();
        let mut callback = TcpStream::connect(addr).unwrap();
        write!(
            callback,
            "GET /callback?code=c0de&state=s1 HTTP/1.1\r\n\r\n"
        )
        .unwrap();
        let code = wait_for_code(
            &listener,
            "s1",
            Duration::from_secs(10),
            Duration::from_millis(200),
        );
        assert_eq!(code.unwrap(), "c0de");
    }

    #[test]
    fn wait_ends_at_the_deadline() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let error = wait_for_code(
            &listener,
            "s1",
            Duration::from_millis(300),
            CONNECTION_READ_TIMEOUT,
        )
        .unwrap_err();
        assert!(error.to_string().contains("No approval"), "{error}");
    }

    /// A stream that returns a fixed request and fails every write, like a closed browser tab.
    struct ClosedTab(std::io::Cursor<&'static [u8]>);

    impl Read for ClosedTab {
        fn read(&mut self, buf: &mut [u8]) -> std::io::Result<usize> {
            self.0.read(buf)
        }
    }

    impl Write for ClosedTab {
        fn write(&mut self, _: &[u8]) -> std::io::Result<usize> {
            Err(std::io::ErrorKind::BrokenPipe.into())
        }
        fn flush(&mut self) -> std::io::Result<()> {
            Err(std::io::ErrorKind::BrokenPipe.into())
        }
    }

    #[test]
    fn a_failed_response_write_keeps_the_code() {
        let stream = ClosedTab(std::io::Cursor::new(
            b"GET /callback?code=c0de&state=s1 HTTP/1.1\r\n\r\n",
        ));
        assert_eq!(handle_callback(stream, "s1"), Some("c0de".to_string()));
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
