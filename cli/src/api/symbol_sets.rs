use anyhow::{anyhow, Context, Result};
use rayon::{
    iter::{IntoParallelIterator, ParallelIterator},
    ThreadPool, ThreadPoolBuilder,
};
use reqwest::blocking::multipart::{Form, Part};
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap, fmt::Debug, iter, num::NonZeroUsize, thread::sleep, time::Duration,
};
use thiserror::Error;
use tracing::{debug, info, warn};

use crate::{
    invocation_context::context,
    utils::{files::content_hash, raise_for_err},
};

const MAX_FILE_SIZE: usize = 100 * 1024 * 1024; // 100 MB
const FINISH_UPLOAD_ERROR_MESSAGE: &str =
    "Failed to finalize symbol upload; maps were not attached";
pub const DEFAULT_UPLOAD_CONCURRENCY: NonZeroUsize = NonZeroUsize::new(10).unwrap();

#[derive(Error, Debug)]
pub enum UploadError {
    #[error("Release ID mismatch: symbol sets already exist with different release IDs")]
    ReleaseIdMismatch,
    #[error("Content mismatch: use --skip-on-conflict or --force")]
    ContentHashMismatch,
    #[error("{0}")]
    Other(#[from] anyhow::Error),
}

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
    /// When true, allow overwriting symbol sets whose content has changed.
    #[serde(default)]
    force: bool,
    /// When true, skip symbol sets whose content changed instead of failing.
    #[serde(default)]
    skip_on_conflict: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadStartResponse {
    id_map: HashMap<String, StartUploadResponseData>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct BulkUploadFinishRequest {
    content_hashes: HashMap<String, String>,
}

/// Upload symbol sets with optional retry on release_id_mismatch error.
/// If `skip_release_on_fail` is true and the server returns a release_id_mismatch error,
/// the upload will be retried without release IDs.
/// If `force` is true, symbol sets whose content has changed are overwritten rather than skipped.
/// If `skip_on_conflict` is true, symbol sets whose content has changed are skipped rather than failing.
pub fn upload_with_retry(
    input_sets: Vec<SymbolSetUpload>,
    batch_size: usize,
    skip_release_on_fail: bool,
    force: bool,
    skip_on_conflict: bool,
) -> Result<()> {
    upload_with_retry_and_concurrency(
        input_sets,
        batch_size,
        skip_release_on_fail,
        force,
        skip_on_conflict,
        DEFAULT_UPLOAD_CONCURRENCY,
    )
}

pub fn upload_with_retry_and_concurrency(
    input_sets: Vec<SymbolSetUpload>,
    batch_size: usize,
    skip_release_on_fail: bool,
    force: bool,
    skip_on_conflict: bool,
    concurrency: NonZeroUsize,
) -> Result<()> {
    let thread_pool = build_upload_thread_pool(concurrency)?;
    let res = upload_inner(
        &input_sets,
        batch_size,
        force,
        skip_on_conflict,
        &thread_pool,
    );
    match res {
        Ok(()) => Ok(()),
        Err(UploadError::ReleaseIdMismatch) if skip_release_on_fail => {
            warn!("Release ID mismatch detected. Retrying upload without release IDs...");
            let sets_without_release: Vec<_> = input_sets
                .into_iter()
                .map(|s| SymbolSetUpload {
                    chunk_id: s.chunk_id.clone(),
                    release_id: None,
                    data: s.data,
                })
                .collect();
            upload_inner(
                &sets_without_release,
                batch_size,
                force,
                skip_on_conflict,
                &thread_pool,
            )
            .map_err(|e| e.into())
        }
        Err(e) => Err(e.into()),
    }
}

fn build_upload_thread_pool(concurrency: NonZeroUsize) -> Result<ThreadPool> {
    ThreadPoolBuilder::new()
        .num_threads(concurrency.get())
        .build()
        .context("Failed to initialize symbol set upload thread pool")
}

fn upload_inner(
    input_sets: &[SymbolSetUpload],
    batch_size: usize,
    force: bool,
    skip_on_conflict: bool,
    thread_pool: &ThreadPool,
) -> Result<(), UploadError> {
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
        let start_response = start_upload(batch, force, skip_on_conflict)?;

        let id_map: HashMap<_, _> = batch.iter().map(|u| (u.chunk_id.as_str(), u)).collect();

        info!(
            "Server returned {} upload keys ({} skipped as already present)",
            start_response.id_map.len(),
            batch.len() - start_response.id_map.len()
        );

        let res: Result<HashMap<String, String>> = thread_pool.install(|| {
            start_response
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
                .collect()
        });

        let content_hashes = res?;

        finish_upload(content_hashes)?;
    }

    Ok(())
}

fn start_upload(
    symbol_sets: &[&SymbolSetUpload],
    force: bool,
    skip_on_conflict: bool,
) -> Result<BulkUploadStartResponse, UploadError> {
    let client = &context().client;

    let request = BulkUploadStartRequest {
        symbol_sets: symbol_sets
            .iter()
            .map(|s| CreateSymbolSetRequest::new(s))
            .collect(),
        force,
        skip_on_conflict,
    };

    let res = retry(retry_policy(500, 2, 3), |_| {
        client.send_post(
            client.project_url("error_tracking/symbol_sets/bulk_start_upload")?,
            |req| req.json(&request),
        )
    });

    match res {
        Ok(response) => Ok(response
            .json()
            .context("Failed to parse start upload response")?),
        Err(e) if e.has_api_error_code("release_id_mismatch") => {
            Err(UploadError::ReleaseIdMismatch)
        }
        Err(e) if e.has_api_error_code("content_hash_mismatch") => {
            Err(UploadError::ContentHashMismatch)
        }
        Err(e) => Err(UploadError::Other(
            anyhow::anyhow!(e).context("Failed to start upload"),
        )),
    }
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

fn finish_upload(content_hashes: HashMap<String, String>) -> Result<(), UploadError> {
    let client = &context().client;
    let request = BulkUploadFinishRequest { content_hashes };

    retry(retry_policy(500, 2, 3), |_| {
        client.send_post(
            client.project_url("error_tracking/symbol_sets/bulk_finish_upload")?,
            |req| req.json(&request),
        )
    })
    .map_err(|e| UploadError::Other(anyhow::anyhow!(e).context(FINISH_UPLOAD_ERROR_MESSAGE)))?;

    Ok(())
}

#[derive(Debug, Deserialize)]
struct DownloadResponse {
    url: String,
}

#[derive(Debug, Deserialize)]
struct SymbolSetListItem {
    id: String,
}

#[derive(Debug, Deserialize)]
struct ListResponse {
    results: Vec<SymbolSetListItem>,
}

/// Resolve a symbol set ref to its ID.
pub fn resolve_ref(symbol_set_ref: &str) -> Result<String> {
    let client = &context().client;
    let encoded_ref = urlencoding::encode(symbol_set_ref);
    let url = client
        .project_url(&format!(
            "error_tracking/symbol_sets/?ref={encoded_ref}&limit=1"
        ))
        .context("Failed to build resolve URL")?;

    let response: ListResponse = client
        .send_get(url, |req| req)
        .context("Failed to resolve symbol set ref")?
        .json()
        .context("Failed to parse resolve response")?;

    response
        .results
        .into_iter()
        .next()
        .map(|s| s.id)
        .context(format!("No symbol set found with ref '{symbol_set_ref}'"))
}

/// Get a presigned download URL for a symbol set.
pub fn get_download_url(symbol_set_id: &str) -> Result<String> {
    // Validate UUID to prevent path traversal
    uuid::Uuid::parse_str(symbol_set_id).context("Invalid symbol set ID: expected a UUID")?;
    let client = &context().client;
    let url = client
        .project_url(&format!(
            "error_tracking/symbol_sets/{symbol_set_id}/download/"
        ))
        .context("Failed to build download URL")?;

    let response: DownloadResponse = client
        .send_get(url, |req| req)
        .context("Failed to get download URL")?
        .json()
        .context("Failed to parse download response")?;

    Ok(response.url)
}

/// Download the raw bytes of a symbol set from S3.
pub fn download_bytes(symbol_set_id: &str) -> Result<Vec<u8>> {
    let presigned_url = get_download_url(symbol_set_id)?;
    let http_client = context().build_http_client()?;

    let response = http_client
        .get(&presigned_url)
        .send()
        .context("Failed to download from S3")?;

    if !response.status().is_success() {
        anyhow::bail!(
            "S3 download failed with status {}",
            response.status().as_u16()
        );
    }

    let bytes = response.bytes().context("Failed to read response body")?;
    Ok(bytes.to_vec())
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
    let mut delays = iterable.peekable();
    while let Some(delay) = delays.next() {
        match func(attempt) {
            Ok(res) => return Ok(res),
            Err(e) => {
                last_error = Some(e);
                attempt += 1;
                warn!("Operation failed: {last_error:?}");
                if delays.peek().is_some() {
                    warn!("Retrying in {delay:?}, attempt {attempt}");
                    sleep(delay);
                }
            }
        }
    }
    Err(last_error.expect("retry called with empty iterator - max_attempts must be > 0"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fmt::Debug,
        sync::{Arc, Mutex},
    };
    use tracing::{field::Visit, Event, Subscriber};
    use tracing_subscriber::{layer::Context, prelude::*, registry::Registry, Layer};

    #[derive(Default)]
    struct MessageVisitor {
        message: Option<String>,
    }

    impl Visit for MessageVisitor {
        fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn Debug) {
            if field.name() == "message" {
                self.message = Some(format!("{value:?}"));
            }
        }

        fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
            if field.name() == "message" {
                self.message = Some(value.to_string());
            }
        }
    }

    #[derive(Clone)]
    struct RecordingLayer {
        messages: Arc<Mutex<Vec<String>>>,
    }

    impl<S: Subscriber> Layer<S> for RecordingLayer {
        fn on_event(&self, event: &Event<'_>, _ctx: Context<'_, S>) {
            let mut visitor = MessageVisitor::default();
            event.record(&mut visitor);
            if let Some(message) = visitor.message {
                self.messages.lock().unwrap().push(message);
            }
        }
    }

    fn capture_tracing_messages<F: FnOnce()>(f: F) -> Vec<String> {
        let messages = Arc::new(Mutex::new(Vec::new()));
        let subscriber = Registry::default().with(RecordingLayer {
            messages: messages.clone(),
        });

        tracing::subscriber::with_default(subscriber, f);

        let captured = messages.lock().unwrap().clone();
        captured
    }

    #[test]
    fn retry_does_not_log_retry_after_final_attempt() {
        let messages = capture_tracing_messages(|| {
            let result: Result<(), &str> = retry(
                vec![Duration::ZERO, Duration::ZERO, Duration::ZERO].into_iter(),
                |_| Err("still broken"),
            );

            assert_eq!(result.unwrap_err(), "still broken");
        });

        let retry_logs = messages
            .iter()
            .filter(|message| message.contains("Retrying in"))
            .count();

        assert_eq!(retry_logs, 2);
    }

    #[test]
    fn upload_thread_pool_uses_configured_concurrency() {
        let thread_pool = build_upload_thread_pool(NonZeroUsize::new(3).unwrap()).unwrap();

        assert_eq!(thread_pool.current_num_threads(), 3);
    }

    #[test]
    fn finish_upload_failure_message_names_unattached_maps() {
        crate::invocation_context::INVOCATION_CONTEXT.get_or_init(|| {
            let config = crate::invocation_context::InvocationConfig {
                api_key: "phx_test".to_string(),
                host: "not a valid url".to_string(),
                env_id: "1".to_string(),
                skip_ssl: false,
                rate_limit: 1000,
            };
            let client = crate::api::client::PHClient::from_config(config.clone()).unwrap();
            crate::invocation_context::InvocationContext::new(config, client)
        });

        let err = finish_upload(HashMap::from([(
            "symbol-set-id".to_string(),
            "content-hash".to_string(),
        )]))
        .unwrap_err();
        let UploadError::Other(err) = err else {
            panic!("expected UploadError::Other");
        };

        let chain = err.chain().map(ToString::to_string).collect::<Vec<_>>();
        assert!(
            chain.iter().any(
                |message| message == "Failed to finalize symbol upload; maps were not attached"
            ),
            "finish_upload error chain should explain that maps were not attached, got {chain:?}"
        );
    }
}
