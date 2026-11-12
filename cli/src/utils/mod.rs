use anyhow::Result;
use reqwest::blocking::Response;
use tracing::error;

use crate::api::client::describe_api_failure;

pub mod auth;
pub mod broken_pipe;
pub mod ci;
pub mod dotenv;
pub mod files;
pub mod git;
pub mod homedir;
pub mod throttler;
pub mod web_url;
pub mod xcode;

pub fn raise_for_err(response: Response) -> Result<Response> {
    if !response.status().is_success() {
        anyhow::bail!(describe_failed_response(response))
    }
    Ok(response)
}

pub fn describe_failed_response(response: Response) -> String {
    let status = response.status().as_u16();
    let url = response.url().clone();
    let body = response.text().unwrap_or_default();

    describe_api_failure(status, &url, &body)
}

pub fn raise_for_presigned_err(response: Response) -> Result<Response> {
    if !response.status().is_success() {
        error!(
            "Request failed: status={} url={}",
            response.status(),
            redact_url(response.url())
        );
        if let Some(summary) = response.text().ok().as_deref().and_then(s3_error_summary) {
            error!("S3 error: {}", summary);
        }
        anyhow::bail!("Request failed")
    }
    Ok(response)
}

pub fn redact_url(url: &reqwest::Url) -> reqwest::Url {
    let mut redacted = url.clone();
    let _ = redacted.set_username("");
    let _ = redacted.set_password(None);
    redacted.set_query(None);
    redacted.set_fragment(None);
    redacted
}

pub fn redact_request_error(mut err: reqwest::Error) -> reqwest::Error {
    if let Some(url) = err.url_mut() {
        *url = redact_url(url);
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
