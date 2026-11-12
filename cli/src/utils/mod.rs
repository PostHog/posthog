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

pub fn redact_request_error(mut err: reqwest::Error) -> reqwest::Error {
    if let Some(url) = err.url_mut() {
        url.set_query(None);
    }
    err
}

fn s3_error_summary(body: &str) -> Option<String> {
    let field = |name: &str| {
        let start = body.find(&format!("<{name}>"))? + name.len() + 2;
        let end = start + body[start..].find(&format!("</{name}>"))?;
        Some(format!("{name}={}", &body[start..end]))
    };
    let fields: Vec<String> = ["Code", "RequestId"]
        .into_iter()
        .filter_map(field)
        .collect();
    (!fields.is_empty()).then(|| fields.join(" "))
}
