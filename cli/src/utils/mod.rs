use anyhow::Result;
use reqwest::blocking::Response;
use tracing::error;

pub mod auth;
pub mod files;
pub mod git;
pub mod homedir;

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
