use core::str;
use std::path::PathBuf;

use anyhow::{anyhow, Context, Ok, Result};
use sha2::Digest;
use tracing::info;

use crate::utils::auth::load_token;
use crate::utils::posthog::capture_command_invoked;
use crate::utils::release::{create_release, CreateReleaseResponse};
use crate::utils::sourcemaps::{read_pairs, ChunkUpload, SourcePair};

pub fn upload(
    host: &str,
    directory: &PathBuf,
    project: Option<String>,
    version: Option<String>,
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

    // See if we have enough information to create a release object
    // TODO - The use of a hash_id here means repeated attempts to upload the same data will fail.
    //        We could relax this, such that we instead replace the existing release with the new one,
    //        or we could even just allow adding new chunks to an existing release, but for now I'm
    //        leaving it like this... Reviewers, lets chat about the right approach here
    let release = create_release(
        host,
        &token,
        Some(directory.clone()),
        Some(content_hash(&uploads)),
        project,
        version,
    )
    .context("While creating release")?;

    upload_chunks(&url, &token.token, uploads, release.as_ref())?;

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

fn upload_chunks(
    url: &str,
    token: &str,
    uploads: Vec<ChunkUpload>,
    release: Option<&CreateReleaseResponse>,
) -> Result<()> {
    let client = reqwest::blocking::Client::new();
    let release_id = release.map(|r| r.id.to_string());
    for upload in uploads {
        info!("Uploading chunk {}", upload.chunk_id);

        let mut params = vec![("chunk_id", &upload.chunk_id)];
        if let Some(id) = &release_id {
            params.push(("release_id", id));
        }

        let res = client
            .post(url)
            .header("Authorization", format!("Bearer {}", token))
            .header("Content-Type", "application/octet-stream")
            .header("Content-Disposition", "attachment; filename='chunk'")
            .query(&params)
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

fn content_hash(uploads: &[ChunkUpload]) -> String {
    let mut hasher = sha2::Sha512::new();
    for upload in uploads {
        hasher.update(&upload.data);
    }
    format!("{:x}", hasher.finalize())
}
