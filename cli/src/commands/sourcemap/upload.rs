use core::str;
use std::collections::HashMap;
use std::path::PathBuf;

use anyhow::{anyhow, bail, Context, Ok, Result};
use reqwest::blocking::multipart::{Form, Part};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use sha2::Digest;
use tracing::{info, warn};

use crate::utils::auth::load_token;
use crate::utils::posthog::capture_command_invoked;
use crate::utils::release::{create_release, CreateReleaseResponse};
use crate::utils::sourcemaps::{read_pairs, ChunkUpload, SourcePair};

const MAX_FILE_SIZE: usize = 100 * 1024 * 1024; // 100 MB

#[derive(Debug, Serialize, Deserialize, Clone)]
struct StartUploadResponseData {
    presigned_url: PresignedUrl,
    symbol_set_id: String,
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PresignedUrl {
    pub url: String,
    pub fields: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadStartRequest {
    release_id: Option<String>,
    chunk_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadStartResponse {
    id_map: HashMap<String, StartUploadResponseData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadFinishRequest {
    content_hashes: HashMap<String, String>,
}

pub fn upload(
    host: Option<String>,
    directory: &PathBuf,
    project: Option<String>,
    version: Option<String>,
    delete_after: bool,
) -> Result<()> {
    let token = load_token().context("While starting upload command")?;
    let host = token.get_host(host.as_deref());

    let capture_handle = capture_command_invoked("sourcemap_upload", Some(&token.env_id));

    let base_url = format!(
        "{}/api/environments/{}/error_tracking/symbol_sets",
        host, token.env_id
    );

    let pairs = read_pairs(directory)?;
    let sourcemap_paths = pairs
        .iter()
        .map(|pair| pair.sourcemap.path.clone())
        .collect::<Vec<_>>();

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
        Some(content_hash(uploads.iter().map(|upload| &upload.data))),
        project,
        version,
    )
    .context("While creating release")?;

    upload_chunks(&base_url, &token.token, uploads, release.as_ref())?;

    if delete_after {
        delete_files(sourcemap_paths).context("While deleting sourcemaps")?;
    }

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
    let chunk_ids = uploads
        .iter()
        .filter(|u| {
            if u.data.len() > MAX_FILE_SIZE {
                warn!(
                    "Skipping chunk {} because the file size is too large ({})",
                    u.chunk_id,
                    u.data.len()
                );
                false
            } else {
                true
            }
        })
        .map(|u| u.chunk_id.clone())
        .collect::<Vec<String>>();

    let start_response = start_upload(&client, base_url, token, chunk_ids, &release_id)?;

    let mut id_map: HashMap<_, _> = uploads
        .into_iter()
        .map(|u| (u.chunk_id.clone(), u))
        .collect();

    let mut content_hashes = HashMap::new();

    for (chunk_id, data) in start_response.id_map.into_iter() {
        info!("Uploading chunk {}", chunk_id);
        let upload = id_map.remove(&chunk_id).ok_or(anyhow!(
            "Got a chunk ID back from posthog that we didn't expect!"
        ))?;

        let content_hash = content_hash([&upload.data]);

        upload_to_s3(&client, data.presigned_url.clone(), upload.data)?;

        content_hashes.insert(data.symbol_set_id.clone(), content_hash);
    }

    finish_upload(&client, base_url, token, content_hashes)?;

    Ok(())
}

fn start_upload(
    client: &Client,
    base_url: &str,
    auth_token: &str,
    chunk_ids: Vec<String>,
    release_id: &Option<String>,
) -> Result<BulkUploadStartResponse> {
    let start_upload_url: String = format!("{}{}", base_url, "/bulk_start_upload");

    let request = BulkUploadStartRequest {
        chunk_ids,
        release_id: release_id.clone(),
    };

    let res = client
        .post(&start_upload_url)
        .header("Authorization", format!("Bearer {}", auth_token))
        .json(&request)
        .send()
        .context(format!("While starting upload to {}", start_upload_url))?;

    if !res.status().is_success() {
        bail!("Failed to start upload: {:?}", res);
    }

    Ok(res.json()?)
}

fn upload_to_s3(client: &Client, presigned_url: PresignedUrl, data: Vec<u8>) -> Result<()> {
    let mut form = Form::new();

    for (key, value) in presigned_url.fields {
        form = form.text(key.clone(), value.clone());
    }

    let part = Part::bytes(data);
    form = form.part("file", part);

    let res = client
        .post(&presigned_url.url)
        .multipart(form)
        .send()
        .context(format!("While uploading chunk to {}", presigned_url.url))?;

    if !res.status().is_success() {
        bail!("Failed to upload chunk: {:?}", res);
    }

    Ok(())
}

fn finish_upload(
    client: &Client,
    base_url: &str,
    auth_token: &str,
    content_hashes: HashMap<String, String>,
) -> Result<()> {
    let finish_upload_url: String = format!("{}/{}", base_url, "bulk_finish_upload");
    let request = BulkUploadFinishRequest { content_hashes };

    let res = client
        .post(finish_upload_url)
        .header("Authorization", format!("Bearer {}", auth_token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .context(format!("While finishing upload to {}", base_url))?;

    if !res.status().is_success() {
        bail!("Failed to finish upload: {:?}", res);
    }

    Ok(())
}

fn content_hash<Iter, Item>(upload_data: Iter) -> String
where
    Iter: IntoIterator<Item = Item>,
    Item: AsRef<[u8]>,
{
    let mut hasher = sha2::Sha512::new();
    for data in upload_data {
        hasher.update(data.as_ref());
    }
    format!("{:x}", hasher.finalize())
}

fn delete_files(paths: Vec<PathBuf>) -> Result<()> {
    // Delete local sourcemaps files from the sourcepair
    for path in paths {
        if path.exists() {
            std::fs::remove_file(&path).context(format!(
                "Failed to delete sourcemaps file: {}",
                path.display()
            ))?;
        }
    }
    Ok(())
}
