use core::str;
use std::path::PathBuf;

use anyhow::{anyhow, Context, Ok, Result};
use tracing::info;

use crate::utils::auth::load_token;
use crate::utils::posthog::capture_command_invoked;
use crate::utils::sourcemaps::{read_pairs, ChunkUpload, SourcePair};

pub fn upload(host: &str, directory: &PathBuf, _build_id: &Option<String>) -> Result<()> {
    let token = load_token().context("While starting upload command")?;

    let capture_handle = capture_command_invoked("sourcemap_upload", Some(&token.env_id));

    let url = format!(
        "{}/api/environments/{}/error_tracking/symbol_sets",
        host, token.env_id
    );

    let pairs = read_pairs(directory)?;

    let uploads = collect_uploads(pairs).context("While preparing files for upload")?;
    info!("Found {} chunks to upload", uploads.len());

    upload_chunks(&url, &token.token, uploads)?;

    let _ = capture_handle.join();

    Ok(())
}

fn collect_uploads(pairs: Vec<SourcePair>) -> Result<Vec<ChunkUpload>> {
    let uploads: Vec<ChunkUpload> = pairs
        .into_iter()
        .map(|pair| pair.into_chunk_upload())
        .collect::<Result<Vec<ChunkUpload>>>()?;
    Ok(uploads)
}

fn upload_chunks(url: &str, token: &str, uploads: Vec<ChunkUpload>) -> Result<()> {
    let client = reqwest::blocking::Client::new();
    for upload in uploads {
        info!("Uploading chunk {}", upload.chunk_id);
        let res = client
            .post(url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/octet-stream")
            .header("Content-Disposition", "attachment; filename='chunk'")
            .query(&[("chunk_id", &upload.chunk_id)])
            .body(upload.data)
            .send()
            .context(format!("While uploading chunk to {}", url))?;

        if !res.status().is_success() {
            return Err(anyhow!("Failed to upload chunk: {:?}", res)
                .context(format!("Chunk id: {}", upload.chunk_id)));
        }
    }

    Ok(())
}
