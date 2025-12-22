use anyhow::{anyhow, Context, Result};
use rayon::iter::{IntoParallelIterator, ParallelIterator};
use reqwest::blocking::multipart::{Form, Part};
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, fmt::Debug, iter, thread::sleep, time::Duration};
use tracing::{debug, info, warn};

use crate::{
    invocation_context::context,
    utils::{files::content_hash, raise_for_err},
};

const MAX_FILE_SIZE: usize = 100 * 1024 * 1024; // 100 MB

#[derive(Debug, Clone)]
pub struct SymbolSetUpload {
    pub chunk_id: String,
    pub release_id: Option<String>,

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
    symbol_sets: Vec<CreateSymbolSetRequest>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadStartResponse {
    id_map: HashMap<String, StartUploadResponseData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadFinishRequest {
    content_hashes: HashMap<String, String>,
}

pub fn upload(input_sets: &[SymbolSetUpload], batch_size: usize) -> Result<()> {
    let upload_requests: Vec<_> = input_sets
        .iter()
        .filter(|s| {
            if s.data.len() > MAX_FILE_SIZE {
                warn!(
                    "Skipping symbol set with id: {}, file too large",
                    s.chunk_id
                );
            }
            s.data.len() <= MAX_FILE_SIZE
        })
        .collect();

    for (i, batch) in upload_requests.chunks(batch_size).enumerate() {
        info!("Starting upload of batch {i}, {} symbol sets", batch.len());
        let start_response = start_upload(batch)?;

        let id_map: HashMap<_, _> = batch.iter().map(|u| (u.chunk_id.as_str(), u)).collect();

        info!(
            "Server returned {} upload keys ({} skipped as already present)",
            start_response.id_map.len(),
            batch.len() - start_response.id_map.len()
        );

        let res: Result<HashMap<String, String>> = start_response
            .id_map
            .into_par_iter()
            .map(|(chunk_id, data)| {
                debug!("uploading chunk {}", chunk_id);
                let upload = id_map.get(chunk_id.as_str()).ok_or(anyhow!(
                    "Got a chunk ID back from posthog that we didn't expect!"
                ))?;

                let content_hash = content_hash([&upload.data]);
                upload_to_s3(data.presigned_url.clone(), &upload.data)?;
                Ok((data.symbol_set_id, content_hash))
            })
            .collect();

        let content_hashes = res?;

        finish_upload(content_hashes)?;
    }

    Ok(())
}

fn start_upload(symbol_sets: &[&SymbolSetUpload]) -> Result<BulkUploadStartResponse> {
    let client = &context().client;

    let request = BulkUploadStartRequest {
        symbol_sets: symbol_sets
            .iter()
            .map(|s| CreateSymbolSetRequest::new(s))
            .collect(),
    };

    let res = retry(retry_policy(500, 2, 3), |_| {
        client.send_post(
            client.project_url("error_tracking/symbol_sets/bulk_start_upload")?,
            |req| req.json(&request),
        )
    })
    .context("Failed to start upload")?;

    Ok(res.json()?)
}

fn upload_to_s3(presigned_url: PresignedUrl, data: &[u8]) -> Result<()> {
    let client = &context().build_http_client()?;
    retry(retry_policy(500, 2, 3), |_| -> Result<()> {
        let mut form = Form::new();
        for (key, value) in &presigned_url.fields {
            form = form.text(key.clone(), value.clone());
        }
        let part = Part::bytes(data.to_vec());
        form = form.part("file", part);

        let response = client.post(&presigned_url.url).multipart(form).send()?;
        raise_for_err(response)?;

        Ok(())
    })
    .context("Failed to upload chunk")?;

    Ok(())
}

fn finish_upload(content_hashes: HashMap<String, String>) -> Result<()> {
    let client = &context().client;
    let request = BulkUploadFinishRequest { content_hashes };

    retry(retry_policy(500, 2, 3), |_| {
        client.send_post(
            client.project_url("error_tracking/symbol_sets/bulk_finish_upload")?,
            |req| req.json(&request),
        )
    })
    .context("Failed to finish upload")?;

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

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CreateSymbolSetRequest {
    chunk_id: String,
    release_id: Option<String>,
    content_hash: String,
}

impl CreateSymbolSetRequest {
    pub fn new(inner: &SymbolSetUpload) -> Self {
        Self {
            chunk_id: inner.chunk_id.clone(),
            release_id: inner.release_id.clone(),
            content_hash: content_hash([&inner.data]),
        }
    }
}

fn retry_policy(duration: u64, factor: u64, max_attempts: usize) -> impl Iterator<Item = Duration> {
    iter::once((duration, factor))
        .cycle()
        .enumerate()
        .map(|(i, (duration, factor))| Duration::from_millis(duration * factor.pow(i as u32)))
        .take(max_attempts)
}

fn retry<I, F, E, R>(iterable: I, mut func: F) -> Result<R, E>
where
    I: Iterator<Item = Duration>,
    F: FnMut(usize) -> Result<R, E>,
    E: Debug,
{
    let mut attempt = 0;
    let mut last_error: Option<E> = None;
    for delay in iterable {
        match func(attempt) {
            Ok(res) => return Ok(res),
            Err(e) => {
                last_error = Some(e);
                attempt += 1;
                warn!("Operation failed: {last_error:?}");
                warn!("Retrying in {delay:?}, attempt {attempt}");
                sleep(delay);
            }
        }
    }
    Err(last_error.expect("retry called with empty iterator - max_attempts must be > 0"))
}
