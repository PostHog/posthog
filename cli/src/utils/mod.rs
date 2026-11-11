use anyhow::Result;
use reqwest::blocking::Response;
use tracing::error;

pub mod auth;
pub mod broken_pipe;
pub mod dotenv;
pub mod files;
pub mod git;
pub mod homedir;
pub mod throttler;
pub mod web_url;
pub mod xcode;

pub fn raise_for_err(response: Response) -> Result<Response> {
    if !response.status().is_success() {
        error!("Request failed: {:?}", response);
        if let Ok(text) = response.text() {
            error!("Response text: {}", text);
        }
        anyhow::bail!("Request failed")
    }
    Ok(response)
}

/// `raise_for_err` for requests to presigned S3 URLs, whose query string or form carries a
/// temporary AWS key ID, session token and signature. Logs the URL without its query and,
/// instead of the body, only the S3 error fields that cannot echo the signed request.
pub fn raise_for_presigned_err(response: Response) -> Result<Response> {
    if !response.status().is_success() {
        let mut url = response.url().clone();
        url.set_query(None);
        error!(
            "Request failed: status={} url={} headers={:?}",
            response.status(),
            url,
            response.headers()
        );
        if let Some(summary) = response.text().ok().as_deref().and_then(s3_error_summary) {
            error!("S3 error: {}", summary);
        }
        anyhow::bail!("Request failed")
    }
    Ok(response)
}

/// Strips the query string from the URL in a presigned request's error, whose message includes it.
pub fn redact_request_error(mut err: reqwest::Error) -> reqwest::Error {
    if let Some(url) = err.url_mut() {
        url.set_query(None);
    }
    err
}

/// Some S3 errors echo the signed request: `SignatureDoesNotMatch` includes the canonical
/// request or the POST policy. These fields never do.
fn s3_error_summary(body: &str) -> Option<String> {
    let field = |name: &str| {
        let start = body.find(&format!("<{name}>"))? + name.len() + 2;
        let end = start + body[start..].find(&format!("</{name}>"))?;
        Some(format!("{name}={}", &body[start..end]))
    };
    let fields: Vec<String> = ["Code", "Message", "RequestId"]
        .into_iter()
        .filter_map(field)
        .collect();
    (!fields.is_empty()).then(|| fields.join(" "))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    const SECRETS: [&str; 3] = ["ASIAEXAMPLEKEYID", "SESSIONTOKEN", "SIGNATURE"];

    fn presigned_url(origin: &str) -> String {
        format!("{origin}/symbolsets/abc?X-Amz-Credential=ASIAEXAMPLEKEYID%2F20261104%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Security-Token=SESSIONTOKEN&X-Amz-Signature=SIGNATURE")
    }

    /// Answers one request the way S3 answers a bad signature, echoing the signed query.
    fn serve_signature_mismatch() -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let origin = format!("http://{}", listener.local_addr().unwrap());
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = Vec::new();
            let mut buf = [0; 1024];
            while !request.ends_with(b"\r\n\r\n") {
                let n = stream.read(&mut buf).unwrap();
                if n == 0 {
                    break;
                }
                request.extend_from_slice(&buf[..n]);
            }
            let body = "<Error><Code>SignatureDoesNotMatch</Code><Message>The request signature we calculated does not match the signature you provided.</Message><AWSAccessKeyId>ASIAEXAMPLEKEYID</AWSAccessKeyId><CanonicalRequest>GET\n/symbolsets/abc\nX-Amz-Security-Token=SESSIONTOKEN&amp;X-Amz-Signature=SIGNATURE</CanonicalRequest><RequestId>REQ123</RequestId></Error>";
            write!(
                stream,
                "HTTP/1.1 403 Forbidden\r\nContent-Type: application/xml\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            )
            .unwrap();
        });
        origin
    }

    #[derive(Clone, Default)]
    struct Logs(Arc<Mutex<Vec<u8>>>);

    impl Write for Logs {
        fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
            self.0.lock().unwrap().write(buf)
        }

        fn flush(&mut self) -> std::io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn presigned_errors_log_without_credentials() {
        let url = presigned_url(&serve_signature_mismatch());
        let response = reqwest::blocking::Client::new().get(&url).send().unwrap();
        let logs = Logs::default();
        let writer = logs.clone();
        let subscriber = tracing_subscriber::fmt()
            .with_writer(move || writer.clone())
            .with_ansi(false)
            .finish();

        let result =
            tracing::subscriber::with_default(subscriber, || raise_for_presigned_err(response));

        assert!(result.is_err());
        let logs = String::from_utf8(logs.0.lock().unwrap().clone()).unwrap();
        assert!(logs.contains("/symbolsets/abc"), "{logs}");
        assert!(logs.contains("Code=SignatureDoesNotMatch"), "{logs}");
        assert!(logs.contains("RequestId=REQ123"), "{logs}");
        for secret in SECRETS {
            assert!(!logs.contains(secret), "{logs}");
        }
    }

    #[test]
    fn transport_errors_drop_the_presigned_query() {
        // The listener is dropped at once, so the connection is refused before any response.
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let origin = format!("http://127.0.0.1:{port}");
        let err = reqwest::blocking::Client::new()
            .get(presigned_url(&origin))
            .send()
            .unwrap_err();
        assert!(err.to_string().contains("SESSIONTOKEN"));

        let message = redact_request_error(err).to_string();

        assert!(
            message.contains(&format!("{origin}/symbolsets/abc")),
            "{message}"
        );
        for secret in SECRETS {
            assert!(!message.contains(secret), "{message}");
        }
    }
}
