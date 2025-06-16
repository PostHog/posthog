use core::str;
use std::path::PathBuf;

use anyhow::{anyhow, Context, Ok, Result};
use reqwest::blocking::Client;
use serde::Deserialize;
use sha2::Digest;
use tracing::{info, warn};

use crate::utils::auth::load_token;
use crate::utils::posthog::capture_command_invoked;
use crate::utils::release::{create_release, CreateReleaseResponse};
use crate::utils::sourcemaps::{read_pairs, ChunkUpload, SourcePair};

const MAX_FILE_SIZE: usize = 100 * 1024 * 1024; // 100 MB

#[derive(Debug, Deserialize)]
struct StartUploadResponseData {
    presigned_url: String,
    symbol_set_id: String,
}

pub fn upload(
    host: Option<String>,
    directory: &PathBuf,
    project: Option<String>,
    version: Option<String>,
) -> Result<()> {
    let token = load_token().context("While starting upload command")?;
    let host = token.get_host(host.as_deref());

    let capture_handle = capture_command_invoked("sourcemap_upload", Some(&token.env_id));

    let base_url = format!(
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
        &host,
        &token,
        Some(directory.clone()),
        Some(content_hash(
            &uploads.iter().map(|upload| &upload.data).collect(),
        )),
        project,
        version,
    )
    .context("While creating release")?;

    upload_chunks(&base_url, &token.token, uploads, release.as_ref())?;

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
    base_url: &str,
    token: &str,
    uploads: Vec<ChunkUpload>,
    release: Option<&CreateReleaseResponse>,
) -> Result<()> {
    let client = reqwest::blocking::Client::new();
    let release_id = release.map(|r| r.id.to_string());
    for upload in uploads {
        info!("Uploading chunk {}", upload.chunk_id);

        let upload_size = upload.data.len();
        if upload_size > MAX_FILE_SIZE {
            warn!(
                "Skipping chunk {} because the file size is too large ({})",
                upload.chunk_id, upload_size
            );
            continue;
        }

        let upload_response =
            request_presigned_url(&client, base_url, token, &upload.chunk_id, &release_id)?;

        // TODO: Not sure if this is the cleanest or if I should just inline the hasher
        let content_hash = content_hash(&vec![&upload.data]);

        upload_to_s3(&client, upload_response.presigned_url, upload.data)?;

        finish_upload(
            &client,
            base_url,
            token,
            upload_response.symbol_set_id,
            content_hash,
        )?;
    }

    Ok(())
}

fn request_presigned_url(
    client: &Client,
    base_url: &str,
    auth_token: &str,
    chunk_id: &str,
    release_id: &Option<String>,
) -> Result<StartUploadResponseData> {
    let start_upload_url: String = format!("{}{}", base_url, "/start_upload");

    let mut params: Vec<(&'static str, &str)> = vec![("chunk_id", chunk_id)];
    if let Some(id) = release_id {
        params.push(("release_id", id));
    }

    let res = client
        .get(&start_upload_url)
        .header("Authorization", format!("Bearer {}", auth_token))
        .query(&params)
        .send()
        .context(format!("While starting upload to {}", start_upload_url))?;

    if !res.status().is_success() {
        return Err(anyhow!("Failed to start upload: {:?}", res));
    }

    let data: StartUploadResponseData = res.json()?;
    Ok(data)
}

fn upload_to_s3(client: &Client, presigned_url: String, data: Vec<u8>) -> Result<()> {
    let res = client
        .put(&presigned_url)
        .body(data)
        .send()
        .context(format!("While uploading chunk to {}", presigned_url))?;

    if !res.status().is_success() {
        return Err(anyhow!("Failed to upload chunk: {:?}", res));
    }

    Ok(())
}

fn finish_upload(
    client: &Client,
    base_url: &str,
    auth_token: &str,
    symbol_set_id: String,
    content_hash: String,
) -> Result<()> {
    let finish_upload_url: String = format!("{}/{}/{}", base_url, symbol_set_id, "finish_upload");
    let params: Vec<(&'static str, &str)> = vec![("content_hash", &content_hash)];

    let res = client
        .get(finish_upload_url)
        .header("Authorization", format!("Bearer {}", auth_token))
        .query(&params)
        .send()
        .context(format!("While finishing upload to {}", base_url))?;

    if !res.status().is_success() {
        return Err(anyhow!("Failed to finish upload: {:?}", res));
    }

    Ok(())
}

fn content_hash(upload_data: &Vec<&Vec<u8>>) -> String {
    let mut hasher = sha2::Sha512::new();
    for data in upload_data {
        hasher.update(data);
    }
    format!("{:x}", hasher.finalize())
}
