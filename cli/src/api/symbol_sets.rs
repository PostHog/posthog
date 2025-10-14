use anyhow::{anyhow, bail, Context, Result};
use rayon::iter::{IntoParallelIterator, ParallelIterator};
use reqwest::blocking::{
    multipart::{Form, Part},
    Client,
};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tracing::{info, warn};

use crate::utils::{
    auth::load_token,
    client::{get_client, SKIP_SSL},
    files::content_hash,
};

const MAX_FILE_SIZE: usize = 100 * 1024 * 1024; // 100 MB

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SymbolSetUpload {
    pub chunk_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub release_id: Option<String>,
    #[serde(skip)]
    pub data: Vec<u8>,
}

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
    symbol_sets: Vec<SymbolSetUpload>,
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
    input_sets: &[SymbolSetUpload],
    batch_size: usize,
    skip_ssl_verification: bool,
) -> Result<()> {
    // TODO - this is just a global setting, set it globally in one place
    *SKIP_SSL.lock().unwrap() = skip_ssl_verification;

    let token = load_token().context("While starting upload command")?;
    let host = token.get_host(host.as_deref());

    let base_url = format!(
        "{}/api/environments/{}/error_tracking/symbol_sets",
        host, token.env_id
    );
    let client = get_client()?;

    let to_upload: Vec<_> = input_sets
        .iter()
        .filter(|s| {
            if s.data.len() > MAX_FILE_SIZE {
                warn!(
                    "Skipping symbol set with id: {}, file too large",
                    s.chunk_id
                );
            }
            s.data.len() < MAX_FILE_SIZE
        })
        .collect();

    for batch in to_upload.chunks(batch_size) {
        let start_response = start_upload(&client, &base_url, &token.token, batch)?;

        let id_map: HashMap<_, _> = batch
            .into_iter()
            .map(|u| (u.chunk_id.as_str(), u))
            .collect();

        let res: Result<HashMap<String, String>> = start_response
            .id_map
            .into_par_iter()
            .map(|(chunk_id, data)| {
                info!("Uploading chunk {}", chunk_id);
                let upload = id_map.get(chunk_id.as_str()).ok_or(anyhow!(
                    "Got a chunk ID back from posthog that we didn't expect!"
                ))?;

                let content_hash = content_hash([&upload.data]);
                upload_to_s3(&client, data.presigned_url.clone(), &upload.data)?;
                Ok((data.symbol_set_id, content_hash))
            })
            .collect();

        let content_hashes = res?;

        finish_upload(&client, &base_url, &token.token, content_hashes)?;
    }

    Ok(())
}

fn start_upload(
    client: &Client,
    base_url: &str,
    auth_token: &str,
    symbol_sets: &[&SymbolSetUpload],
) -> Result<BulkUploadStartResponse> {
    let start_upload_url: String = format!("{}{}", base_url, "/bulk_start_upload");

    let request = BulkUploadStartRequest {
        symbol_sets: symbol_sets.iter().map(|s| s.cheap_clone()).collect(),
    };

    let res = client
        .post(&start_upload_url)
        .header("Authorization", format!("Bearer {auth_token}"))
        .json(&request)
        .send()
        .context(format!("While starting upload to {start_upload_url}"))?;

    if !res.status().is_success() {
        bail!("Failed to start upload: {:?}", res);
    }

    Ok(res.json()?)
}

fn upload_to_s3(client: &Client, presigned_url: PresignedUrl, data: &[u8]) -> Result<()> {
    let mut last_err = None;
    let mut delay = std::time::Duration::from_millis(500);
    for attempt in 1..=3 {
        let mut form = Form::new();
        for (key, value) in &presigned_url.fields {
            form = form.text(key.clone(), value.clone());
        }
        let part = Part::bytes(data.to_vec());
        form = form.part("file", part);

        let res = client.post(&presigned_url.url).multipart(form).send();

        match res {
            Result::Ok(resp) if resp.status().is_success() => {
                return Ok(());
            }
            Result::Ok(resp) => {
                last_err = Some(anyhow!("Failed to upload chunk: {:?}", resp));
            }
            Result::Err(e) => {
                last_err = Some(anyhow!("Failed to upload chunk: {}", e));
            }
        }
        if attempt < 3 {
            warn!(
                "Upload attempt {} failed, retrying in {:?}...",
                attempt, delay
            );
            std::thread::sleep(delay);
            delay *= 2;
        }
    }
    Err(last_err.unwrap_or_else(|| anyhow!("Unknown error during upload")))
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
        .header("Authorization", format!("Bearer {auth_token}"))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()
        .context(format!("While finishing upload to {base_url}"))?;

    if !res.status().is_success() {
        bail!("Failed to finish upload: {:?}", res);
    }

    Ok(())
}

impl SymbolSetUpload {
    pub fn cheap_clone(&self) -> Self {
        Self {
            chunk_id: self.chunk_id.clone(),
            release_id: self.release_id.clone(),
            data: vec![],
        }
    }
}
