use anyhow::{anyhow, Context, Result};
use rayon::{
    iter::{IntoParallelIterator, IntoParallelRefIterator, ParallelIterator},
    ThreadPool, ThreadPoolBuilder,
};
use reqwest::blocking::multipart::{Form, Part};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::{
    collections::HashMap,
    fmt::Debug,
    iter,
    num::NonZeroUsize,
    sync::atomic::{AtomicBool, Ordering},
    thread::sleep,
    time::Duration,
};
use thiserror::Error;
use tracing::{debug, info, warn};

use crate::{
    invocation_context::context,
    utils::{files::content_hash, raise_for_err},
};

pub(crate) const MAX_FILE_SIZE: usize = 100 * 1024 * 1024; // 100 MB
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

    /// Precomputed hash for the server's skip-identical-content check; `None` hashes `data`
    /// as-is. Set this when `data` contains bytes that vary between builds of identical code
    /// (e.g. an injected release id), so unchanged chunks still skip re-upload.
    pub content_hash: Option<String>,
}

/// Coalesce uploads that share a chunk_id, keeping the first occurrence. Bulk start rejects a
/// batch with a repeated id, before it filters out the chunks the server already has.
pub fn dedup_uploads_by_chunk_id(uploads: Vec<SymbolSetUpload>) -> Vec<SymbolSetUpload> {
    let mut seen = std::collections::HashSet::new();
    let mut deduped = Vec::with_capacity(uploads.len());
    for upload in uploads {
        if seen.insert(upload.chunk_id.clone()) {
            deduped.push(upload);
        } else {
            warn!(
                "Duplicate chunk id {} across symbol sets; keeping the first",
                upload.chunk_id
            );
        }
    }
    deduped
}

/// Per-run tally of what an upload actually did. Without it a run that skipped
/// every chunk is indistinguishable from one that uploaded every chunk, since
/// both just exit zero.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct UploadSummary {
    pub uploaded: usize,
    pub skipped_already_present: usize,
    pub skipped_too_large: usize,
}

impl UploadSummary {
    pub fn skipped(&self) -> usize {
        self.skipped_already_present + self.skipped_too_large
    }

    pub fn telemetry_props(&self) -> Vec<(&'static str, serde_json::Value)> {
        vec![
            ("uploaded", serde_json::json!(self.uploaded)),
            (
                "skipped_already_present",
                serde_json::json!(self.skipped_already_present),
            ),
            (
                "skipped_too_large",
                serde_json::json!(self.skipped_too_large),
            ),
        ]
    }

    fn log(&self) {
        info!(
            "Upload summary: {} chunk(s) uploaded, {} skipped ({} already present, {} too large)",
            self.uploaded,
            self.skipped(),
            self.skipped_already_present,
            self.skipped_too_large
        );
    }
}

#[derive(Debug, Serialize, Deserialize, Clone)]
struct StartUploadResponseData {
    presigned_url: PresignedUrl,
    /// Standard-endpoint presigned POST, sent when `presigned_url` targets the
    /// S3 transfer-acceleration endpoint. Absent on older servers.
    fallback_presigned_url: Option<PresignedUrl>,
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
///
/// The summary is returned beside the result rather than inside it, because a
/// failed run still needs to report the chunks it uploaded and skipped before
/// it gave up.
pub fn upload_with_retry(
    input_sets: Vec<SymbolSetUpload>,
    batch_size: usize,
    skip_release_on_fail: bool,
    force: bool,
    skip_on_conflict: bool,
) -> (UploadSummary, Result<()>) {
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
) -> (UploadSummary, Result<()>) {
    let mut summary = UploadSummary::default();
    let thread_pool = match build_upload_thread_pool(concurrency) {
        Ok(thread_pool) => thread_pool,
        Err(e) => return (summary, Err(e)),
    };
    let transport = match context()
        .build_upload_http_client()
        .context("Failed to initialize upload HTTP client")
    {
        Ok(client) => UploadTransport {
            client,
            accelerated_unreachable: AtomicBool::new(false),
        },
        Err(e) => return (summary, Err(e)),
    };
    let res = upload_inner(
        &input_sets,
        batch_size,
        force,
        skip_on_conflict,
        &thread_pool,
        &transport,
        &mut summary,
    );
    let res = match res {
        Err(UploadError::ReleaseIdMismatch) if skip_release_on_fail => {
            warn!("Release ID mismatch detected. Retrying upload without release IDs...");
            // Batches finalized before the mismatch are on the server by the time
            // the retry runs, so upload_inner recounts them as already present.
            // Remember them and reclassify below, because this run did upload them.
            let uploaded_before_retry = summary.uploaded;
            let sets_without_release: Vec<_> = input_sets
                .into_iter()
                .map(|s| SymbolSetUpload {
                    chunk_id: s.chunk_id.clone(),
                    release_id: None,
                    data: s.data,
                    content_hash: s.content_hash,
                })
                .collect();
            let res = upload_inner(
                &sets_without_release,
                batch_size,
                force,
                skip_on_conflict,
                &thread_pool,
                &transport,
                &mut summary,
            );
            summary.uploaded += uploaded_before_retry;
            summary.skipped_already_present = summary
                .skipped_already_present
                .saturating_sub(uploaded_before_retry);
            res
        }
        res => res,
    };

    // Logged on failure too, so a partial run still reports how far it got.
    summary.log();

    (summary, res.map_err(Into::into))
}

fn build_upload_thread_pool(concurrency: NonZeroUsize) -> Result<ThreadPool> {
    ThreadPoolBuilder::new()
        .num_threads(concurrency.get())
        .build()
        .context("Failed to initialize symbol set upload thread pool")
}

/// Shared S3 upload transport for one run: a single client, because reusing its
/// connection pool avoids paying a TCP + TLS handshake per uploaded chunk, and
/// the run-wide latch that stops attempts against the accelerated endpoint once
/// it is known to be unreachable.
struct UploadTransport {
    client: Client,
    accelerated_unreachable: AtomicBool,
}

impl UploadTransport {
    /// Flips the latch. Logs and reports the switch only on the first call, so
    /// concurrent chunks cannot duplicate the notice.
    fn mark_accelerated_unreachable(&self) {
        if !self.accelerated_unreachable.swap(true, Ordering::Relaxed) {
            warn!("Can't reach the accelerated S3 endpoint. Uploading the remaining chunks through the standard S3 endpoint.");
            context().capture_event(
                "error_tracking_cli_sourcemaps_upload_endpoint_fallback",
                Vec::new(),
            );
        }
    }
}

fn upload_inner(
    input_sets: &[SymbolSetUpload],
    batch_size: usize,
    force: bool,
    skip_on_conflict: bool,
    thread_pool: &ThreadPool,
    transport: &UploadTransport,
    summary: &mut UploadSummary,
) -> Result<(), UploadError> {
    // A release-id-mismatch retry re-uploads the same sets from scratch, so the
    // tally starts over rather than double-counting the first attempt.
    *summary = UploadSummary::default();

    let upload_requests: Vec<_> = input_sets
        .iter()
        .filter(|s| {
            if s.data.len() > MAX_FILE_SIZE {
                summary.skipped_too_large += 1;
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
        // Hash each payload once, across the pool — the same hash is sent in the
        // start request and used to confirm the upload when finishing.
        let content_hashes: Vec<String> = thread_pool.install(|| {
            batch
                .par_iter()
                .map(|u| {
                    u.content_hash
                        .clone()
                        .unwrap_or_else(|| content_hash([&u.data]))
                })
                .collect()
        });
        let start_response = start_upload(batch, &content_hashes, force, skip_on_conflict)?;

        let id_map: HashMap<_, _> = batch
            .iter()
            .zip(content_hashes.iter())
            .map(|(u, hash)| (u.chunk_id.as_str(), (u, hash)))
            .collect();

        summary.skipped_already_present += batch.len() - start_response.id_map.len();
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
                    let (upload, content_hash) = id_map.get(chunk_id.as_str()).ok_or(anyhow!(
                        "Got a chunk ID back from posthog that we didn't expect!"
                    ))?;

                    upload_to_s3(
                        transport,
                        &data.presigned_url,
                        data.fallback_presigned_url.as_ref(),
                        &upload.data,
                    )?;
                    Ok((data.symbol_set_id, (*content_hash).clone()))
                })
                .collect()
        });

        let content_hashes = res?;
        let uploaded = content_hashes.len();

        finish_upload(content_hashes)?;
        summary.uploaded += uploaded;
    }

    Ok(())
}

fn start_upload(
    symbol_sets: &[&SymbolSetUpload],
    content_hashes: &[String],
    force: bool,
    skip_on_conflict: bool,
) -> Result<BulkUploadStartResponse, UploadError> {
    let client = &context().client;

    let request = BulkUploadStartRequest {
        symbol_sets: symbol_sets
            .iter()
            .zip(content_hashes.iter())
            .map(|(s, hash)| CreateSymbolSetRequest {
                chunk_id: s.chunk_id.clone(),
                release_id: s.release_id.clone(),
                content_hash: hash.clone(),
            })
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

/// Transport errors the primary URL gets before an attempt is routed to the
/// fallback URL. The first reset can come from a stale pooled connection, so
/// only a fresh connection that also fails counts as evidence that the
/// accelerated endpoint is blocked.
const PRIMARY_TRANSPORT_ERRORS_BEFORE_FALLBACK: usize = 2;

/// Attempts the fallback URL gets after the primary budget, so one transient
/// error on the fallback does not fail the chunk.
const FALLBACK_ATTEMPTS: usize = 2;

/// Per-chunk routing state: which URL the next attempt should use, and whether
/// a fallback success is strong enough evidence to flip the run-wide
/// accelerated-endpoint latch.
#[derive(Debug, Default)]
struct EndpointRouter {
    primary_transport_errors: usize,
    fallback_had_transport_error: bool,
}

impl EndpointRouter {
    fn use_fallback(&self, latch_set: bool) -> bool {
        latch_set || self.primary_transport_errors >= PRIMARY_TRANSPORT_ERRORS_BEFORE_FALLBACK
    }

    fn record_transport_error(&mut self, used_fallback: bool) {
        if used_fallback {
            self.fallback_had_transport_error = true;
        } else {
            self.primary_transport_errors += 1;
        }
    }

    /// A response from the primary endpoint disproves the blocked-endpoint
    /// hypothesis, so only consecutive transport errors count as evidence.
    fn record_primary_response(&mut self) {
        self.primary_transport_errors = 0;
    }

    /// A fallback success flips the latch only when the primary failed at the
    /// transport level while the fallback never did; transport errors on both
    /// URLs point at a generally unreliable network rather than a blocked
    /// accelerated endpoint.
    fn should_set_latch(&self, used_fallback: bool) -> bool {
        used_fallback
            && !self.fallback_had_transport_error
            && self.primary_transport_errors >= PRIMARY_TRANSPORT_ERRORS_BEFORE_FALLBACK
    }
}

fn upload_to_s3(
    transport: &UploadTransport,
    presigned_url: &PresignedUrl,
    fallback_presigned_url: Option<&PresignedUrl>,
    data: &[u8],
) -> Result<()> {
    let mut router = EndpointRouter::default();

    // Without a fallback URL keep the original budget of 3 attempts.
    let max_attempts = if fallback_presigned_url.is_some() {
        PRIMARY_TRANSPORT_ERRORS_BEFORE_FALLBACK + FALLBACK_ATTEMPTS
    } else {
        3
    };

    retry(retry_policy(500, 2, max_attempts), |_| -> Result<()> {
        let latch_set = transport.accelerated_unreachable.load(Ordering::Relaxed);
        let target_fallback = fallback_presigned_url.filter(|_| router.use_fallback(latch_set));
        let use_fallback = target_fallback.is_some();
        let target = target_fallback.unwrap_or(presigned_url);

        let mut form = Form::new();
        for (key, value) in &target.fields {
            form = form.text(key.clone(), value.clone());
        }
        // The filename is required: Go-based S3 implementations (SeaweedFS, MinIO)
        // only treat a multipart part as a file upload when Content-Disposition
        // carries a filename. Without it the part is parsed as a form field, which
        // is memory-capped, so uploads over a few MB fail with MalformedPOSTRequest.
        // AWS S3 accepts both forms.
        let part = Part::bytes(data.to_vec()).file_name("file");
        form = form.part("file", part);

        let response = match transport.client.post(&target.url).multipart(form).send() {
            Ok(response) => response,
            Err(e) => {
                router.record_transport_error(use_fallback);
                return Err(e.into());
            }
        };
        if !use_fallback {
            router.record_primary_response();
        }
        // HTTP errors never reroute: a response proves the endpoint is
        // reachable, and the standard endpoint would return the same error.
        raise_for_err(response)?;

        if router.should_set_latch(use_fallback) {
            transport.mark_accelerated_unreachable();
        }

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
            content_hash: self.content_hash.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CreateSymbolSetRequest {
    chunk_id: String,
    release_id: Option<String>,
    content_hash: String,
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
        sync::{Arc, Mutex, MutexGuard},
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

    // `tracing` caches each callsite's `Interest` in process-global state, resolved against
    // whichever thread reaches the callsite first. A test that drives `retry` with no subscriber
    // installed caches "never" on `retry`'s `warn!` callsites, so a concurrent
    // `capture_tracing_messages` silently observes none of the events it asserts on. Serialize
    // every test that reaches those callsites so registration happens under a known subscriber.
    static RETRY_TRACING_LOCK: Mutex<()> = Mutex::new(());

    fn lock_retry_tracing() -> MutexGuard<'static, ()> {
        RETRY_TRACING_LOCK
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner())
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
        let _retry_tracing_lock = lock_retry_tracing();

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
    fn endpoint_router_switches_to_fallback_after_two_primary_transport_errors() {
        let mut router = EndpointRouter::default();
        assert!(!router.use_fallback(false));
        router.record_transport_error(false);
        assert!(!router.use_fallback(false));
        router.record_transport_error(false);
        assert!(router.use_fallback(false));
    }

    #[test]
    fn endpoint_router_counts_only_consecutive_primary_transport_errors() {
        let mut router = EndpointRouter::default();
        router.record_transport_error(false);
        router.record_primary_response();
        router.record_transport_error(false);
        assert!(!router.use_fallback(false));
        assert!(!router.should_set_latch(true));
    }

    #[test]
    fn endpoint_router_uses_fallback_immediately_when_latch_is_set() {
        let router = EndpointRouter::default();
        assert!(router.use_fallback(true));
    }

    #[test]
    fn endpoint_router_latch_requires_clean_fallback_after_primary_transport_errors() {
        let mut router = EndpointRouter::default();
        assert!(!router.should_set_latch(true));
        router.record_transport_error(false);
        router.record_transport_error(false);
        assert!(!router.should_set_latch(false));
        assert!(router.should_set_latch(true));
        router.record_transport_error(true);
        assert!(!router.should_set_latch(true));
    }

    #[test]
    fn start_upload_response_parses_without_fallback_presigned_url() {
        let json = r#"{"id_map":{"chunk":{"presigned_url":{"url":"https://example.com/","fields":{}},"symbol_set_id":"id"}}}"#;
        let parsed: BulkUploadStartResponse = serde_json::from_str(json).unwrap();
        assert!(parsed.id_map["chunk"].fallback_presigned_url.is_none());
    }

    #[test]
    fn upload_thread_pool_uses_configured_concurrency() {
        let thread_pool = build_upload_thread_pool(NonZeroUsize::new(3).unwrap()).unwrap();

        assert_eq!(thread_pool.current_num_threads(), 3);
    }

    #[test]
    fn finish_upload_failure_message_names_unattached_maps() {
        // `finish_upload` retries, so it reaches the callsites `RETRY_TRACING_LOCK` protects.
        let _retry_tracing_lock = lock_retry_tracing();

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
