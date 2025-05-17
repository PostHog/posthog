use crate::utils::auth::load_token;
use crate::utils::posthog::capture_command_invoked;
use crate::utils::sourcemaps::{ChunkUpload, SourcePair, read_pairs};

use std::path::PathBuf;
use anyhow::{anyhow, Context, Result};
use reqwest::blocking::Client;
use std::{thread, time::Duration};
use tracing::{info, warn};

pub fn upload(
    host: &str, 
    directory: &PathBuf, 
    _build_id: &Option<String>,
    timeout: u64,
    retry_interval: u64,
    retries: u32
) -> Result<()> {
    let token = load_token().context("While starting upload command")?;

    let capture_handle = capture_command_invoked("sourcemap_upload", Some(&token.env_id));

    let url = format!(
        "{}/api/environments/{}/error_tracking/symbol_sets",
        host, token.env_id
    );

    let pairs = read_pairs(directory)?;

    let uploads = collect_uploads(pairs).context("While preparing files for upload")?;
    info!("Found {} chunks to upload", uploads.len());

    // Call the (now modified) `upload_chunks` local helper function with the new parameters
    upload_chunks(&url, &token.token, uploads, timeout, retry_interval, retries)?;

    let _ = capture_handle.join();

    Ok(())
}

// This helper function remains as it was in your original code.
// It uses `SourcePair` and `ChunkUpload` imported from `crate::utils::sourcemaps`.
fn collect_uploads(pairs: Vec<SourcePair>) -> Result<Vec<ChunkUpload>> {
    let uploads: Vec<ChunkUpload> = pairs
        .into_iter()
        .map(|pair| pair.into_chunk_upload()) // Assumes SourcePair has this method
        .collect::<Result<Vec<ChunkUpload>>>()?; // Collect into a Result of a Vec
    Ok(uploads)
}

fn upload_chunks(
    url: &str, 
    token: &str, 
    uploads: Vec<ChunkUpload>,
    timeout: u64,
    retry_interval: u64,
    max_retries: u32
) -> Result<()> {
    let client = Client::builder()
        .timeout(Duration::from_secs(timeout))
        .build()
        .context("Failed to build reqwest HTTP client")?;

    for upload in uploads {
        let mut attempts = 0;
        loop {
            attempts += 1;
            info!(
                "Uploading chunk {} (Attempt {}/{})",
                upload.chunk_id, attempts, max_retries
            );

            let body_data = upload.data.clone();

            let request_builder = client
                .post(url)
                .header("Authorization", format!("Bearer {}", token))
                .header("Content-Type", "application/octet-stream")
                .header("Content-Disposition", "attachment; filename='chunk'")
                .query(&[("chunk_id", &upload.chunk_id)])
                .body(body_data);

            match request_builder.send() {
                std::result::Result::Ok(res) => {
                    if res.status().is_success() {
                        info!("Successfully uploaded chunk {}", upload.chunk_id);
                        break;
                    } else {
                        let status = res.status();
                        let error_body = res
                            .text()
                            .unwrap_or_else(|_| "Could not retrieve error body".to_string());
                        warn!(
                            "Failed to upload chunk {}: HTTP Status {} - {}",
                            upload.chunk_id, status, error_body
                        );
                        return Err(anyhow!(
                            "Upload failed for chunk {}: HTTP Status {} - {}",
                            upload.chunk_id,
                            status,
                            error_body
                        ));
                    }
                }
                Err(err) => {
                    if err.is_timeout() || err.is_connect() || err.is_request() {
                        warn!(
                            "Error uploading chunk {}: {}. (Attempt {}/{})",
                            upload.chunk_id, err, attempts, max_retries
                        );
                        if attempts >= max_retries {
                            return Err(anyhow!(err).context(format!(
                                "Failed to upload chunk {} after {} attempts",
                                upload.chunk_id, max_retries
                            )));
                        }
                        let delay_seconds = retry_interval * attempts as u64;
                        info!("Retrying chunk {} in {}s...", upload.chunk_id, delay_seconds);
                        thread::sleep(Duration::from_secs(delay_seconds));
                    } else {
                        return Err(anyhow!(err).context(format!(
                            "Non-recoverable error while attempting to upload chunk {}",
                            upload.chunk_id
                        )));
                    }
                }
            }
        }
    }

    Ok(())
}