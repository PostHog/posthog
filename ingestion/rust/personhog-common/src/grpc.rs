use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};
use std::time::Instant;

use http::{HeaderValue, Request, Response};
use metrics::{counter, gauge, histogram};
use pin_project::{pin_project, pinned_drop};
use tokio::task::futures::TaskLocalFuture;
use tonic::metadata::MetadataValue;
use tower::{Layer, Service};

use crate::storage_error::TimeoutKind;

pub use common_grpc::{
    tracked_tcp_incoming, tracked_tcp_incoming_until, until_incoming_ends, GrpcLoadShedFuture,
    GrpcLoadShedLayer, GrpcLoadShedService, TrackedTcpStream, WaiterSlot, PROCESSING_TIME_HEADER,
};

// ============================================================
// Client name extraction
// ============================================================

/// Header name for client identification in gRPC metadata.
pub const CLIENT_NAME_HEADER: &str = "x-client-name";

/// Metadata key marking a FAILED_PRECONDITION as a definitive semantic
/// refusal rather than a routing-race rejection. The router bounces and
/// retries bare FAILED_PRECONDITION (handoff fences, ownership races,
/// person fences — conditions that clear in watch or healer time) and
/// surfaces exhaustion as retriable UNAVAILABLE; a response carrying this
/// key is a final answer about the request itself and must pass through
/// to the caller unchanged, or a fail-closed refusal degrades into an
/// infinite retry loop. The value is a short reason slug for
/// observability.
pub const SEMANTIC_REFUSAL_METADATA_KEY: &str = "x-semantic-refusal";

/// Never set where the request may have been applied.
pub use common_grpc::NOT_APPLIED_HEADER;

/// Marks a DEADLINE_EXCEEDED that a Postgres timeout caused, rather than an
/// expired gRPC deadline. The value names the setting that fired:
/// `statement_timeout` or `lock_timeout`.
pub const DB_TIMEOUT_METADATA_KEY: &str = "x-db-timeout";

pub fn db_timeout_status(message: impl Into<String>, kind: TimeoutKind) -> tonic::Status {
    let mut status = tonic::Status::deadline_exceeded(message.into());
    status.metadata_mut().insert(
        DB_TIMEOUT_METADATA_KEY,
        MetadataValue::from_static(kind.as_str()),
    );
    status
}

/// Build a semantic refusal. The reason is a short slug used as a metric
/// label.
pub fn semantic_refusal(message: impl Into<String>, reason: &'static str) -> tonic::Status {
    let mut status = tonic::Status::failed_precondition(message.into());
    if let Ok(value) = reason.parse() {
        status
            .metadata_mut()
            .insert(SEMANTIC_REFUSAL_METADATA_KEY, value);
    }
    status
}

/// Whether a status is a definitive semantic refusal rather than a
/// transient failure a retry can outlive.
pub fn is_semantic_refusal(status: &tonic::Status) -> bool {
    status.code() == tonic::Code::FailedPrecondition
        && status
            .metadata()
            .contains_key(SEMANTIC_REFUSAL_METADATA_KEY)
}

/// The refusal's reason slug, when present.
pub fn semantic_refusal_reason(status: &tonic::Status) -> Option<&str> {
    status
        .metadata()
        .get(SEMANTIC_REFUSAL_METADATA_KEY)
        .and_then(|v| v.to_str().ok())
}

/// The refusal reason as a metric label: bounded and character-safe, so a
/// misbehaving peer cannot mint unbounded label cardinality or break the
/// metric encoding. Falls back to "unknown".
pub fn refusal_reason_label(status: &tonic::Status) -> &str {
    semantic_refusal_reason(status)
        .filter(|r| {
            r.len() <= 64
                && r.chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '-' | '_'))
        })
        .unwrap_or("unknown")
}

/// Header name for caller-tag attribution in gRPC metadata.
/// Identifies the code path / feature area within a service that
/// triggered the request (e.g., "api/feature-flags", "celery/cohort-calculation").
const CALLER_TAG_HEADER: &str = "x-caller-tag";

tokio::task_local! {
    /// Per-request client name, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_client_name()`.
    pub static CLIENT_NAME: Arc<str>;

    /// Per-request caller tag, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_caller_tag()`.
    pub static CALLER_TAG: Arc<str>;

    /// Per-request gRPC method name, set by `GrpcMetricsLayer` and readable
    /// anywhere in the request's async call chain via `current_method_name()`.
    pub static METHOD_NAME: Arc<str>;
}

/// Get the current client name from the task-local, or `"unknown"` if not set.
/// Returns `Arc<str>` so cloning is a cheap refcount bump rather than a
/// heap allocation + memcpy on every call.
pub fn current_client_name() -> Arc<str> {
    CLIENT_NAME
        .try_with(|c| c.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Get the current caller tag from the task-local, or `"unknown"` if not set.
pub fn current_caller_tag() -> Arc<str> {
    CALLER_TAG
        .try_with(|t| t.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Get the current gRPC method name from the task-local, or `"unknown"` if not set.
pub fn current_method_name() -> Arc<str> {
    METHOD_NAME
        .try_with(|m| m.clone())
        .unwrap_or_else(|_| Arc::from("unknown"))
}

/// Label for a failure carrying no gRPC status at all — a client-side
/// error (a serialization failure, say) rather than anything a server
/// said. Part of the same label vocabulary as [`code_as_str`], and
/// deliberately distinct from its `unknown`, which is a real code a
/// server can return.
pub const NON_STATUS: &str = "non_status";

/// Stable snake_case name for a gRPC status code, for use as a metric
/// label. Codes are a fixed vocabulary, which is what makes them safe to
/// label with; status *messages* never are. Shared so every service
/// labels the same failure the same way — a dashboard comparing a
/// client's view of an error against the router's should not have to
/// translate between two spellings. Callers that classify errors which
/// may carry no status at all complete the vocabulary with
/// [`NON_STATUS`].
pub fn code_as_str(code: tonic::Code) -> &'static str {
    use tonic::Code;
    match code {
        Code::Ok => "ok",
        Code::Cancelled => "cancelled",
        Code::Unknown => "unknown",
        Code::InvalidArgument => "invalid_argument",
        Code::DeadlineExceeded => "deadline_exceeded",
        Code::NotFound => "not_found",
        Code::AlreadyExists => "already_exists",
        Code::PermissionDenied => "permission_denied",
        Code::ResourceExhausted => "resource_exhausted",
        Code::FailedPrecondition => "failed_precondition",
        Code::Aborted => "aborted",
        Code::OutOfRange => "out_of_range",
        Code::Unimplemented => "unimplemented",
        Code::Internal => "internal",
        Code::Unavailable => "unavailable",
        Code::DataLoss => "data_loss",
        Code::Unauthenticated => "unauthenticated",
    }
}

const MAX_HEADER_TAG_LEN: usize = 128;

fn is_safe_tag_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '/' | '_' | '-' | ':' | '.')
}

fn sanitize_header_tag(raw: &str) -> &str {
    let s = if raw.len() > MAX_HEADER_TAG_LEN {
        &raw[..MAX_HEADER_TAG_LEN]
    } else {
        raw
    };
    if s.chars().all(is_safe_tag_char) {
        s
    } else {
        "unknown"
    }
}

fn extract_sanitized_header<B>(request: &Request<B>, header: &str) -> Arc<str> {
    request
        .headers()
        .get(header)
        .and_then(|v| v.to_str().ok())
        .filter(|s| !s.is_empty())
        .map(sanitize_header_tag)
        .unwrap_or("unknown")
        .into()
}

fn extract_client_name<B>(request: &Request<B>) -> Arc<str> {
    extract_sanitized_header(request, CLIENT_NAME_HEADER)
}

fn extract_caller_tag<B>(request: &Request<B>) -> Arc<str> {
    extract_sanitized_header(request, CALLER_TAG_HEADER)
}

// ============================================================
// Client-side in-flight tracking
// ============================================================

/// Drop guard that decrements a client-side in-flight gauge on drop,
/// ensuring cancellation-safety for outbound request tracking.
pub struct ClientInFlightGuard {
    pub backend: &'static str,
    client: Arc<str>,
}

impl ClientInFlightGuard {
    pub fn new(backend: &'static str) -> Self {
        let client = current_client_name();
        gauge!("personhog_router_client_requests_in_flight", "backend" => backend, "client" => client.clone())
            .increment(1.0);
        Self { backend, client }
    }
}

impl Drop for ClientInFlightGuard {
    fn drop(&mut self) {
        gauge!("personhog_router_client_requests_in_flight", "backend" => self.backend, "client" => self.client.clone())
            .decrement(1.0);
    }
}

// ============================================================
// Request metrics layer
// ============================================================

/// Response header set by [`AsyncGzipLayer`] with the total gzip layer
/// overhead in milliseconds (body collection + compression). The router
/// subtracts this alongside `PROCESSING_TIME_HEADER` to isolate true
/// network RTT.
pub const GZIP_OVERHEAD_HEADER: &str = "x-gzip-overhead-ms";

/// Tower layer that instruments gRPC requests with timing and concurrency metrics.
///
/// Records:
/// - `grpc_server_requests_total` - counter with method and client labels
/// - `grpc_server_request_duration_ms` - histogram with method and client labels
/// - `grpc_server_requests_in_flight` - gauge with method and client labels
///
/// Also sets the `CLIENT_NAME` task-local so downstream code can read
/// the client name via `current_client_name()`.
#[derive(Clone, Default)]
pub struct GrpcMetricsLayer {
    emit_processing_time_header: bool,
}

impl GrpcMetricsLayer {
    pub fn with_processing_time_header(self) -> Self {
        Self {
            emit_processing_time_header: true,
        }
    }
}

impl<S> Layer<S> for GrpcMetricsLayer {
    type Service = GrpcMetricsService<S>;

    fn layer(&self, service: S) -> Self::Service {
        GrpcMetricsService {
            inner: service,
            emit_processing_time_header: self.emit_processing_time_header,
        }
    }
}

#[derive(Clone)]
pub struct GrpcMetricsService<S> {
    inner: S,
    emit_processing_time_header: bool,
}

impl<S, ReqBody, ResBody> Service<Request<ReqBody>> for GrpcMetricsService<S>
where
    S: Service<Request<ReqBody>, Response = Response<ResBody>> + Clone + Send + 'static,
    S::Future: Send,
    S::Error: Send,
    ReqBody: Send + 'static,
    ResBody: Send + 'static,
{
    type Response = S::Response;
    type Error = S::Error;
    type Future = GrpcMetricsFuture<S::Future>;

    fn poll_ready(&mut self, cx: &mut Context<'_>) -> Poll<Result<(), Self::Error>> {
        self.inner.poll_ready(cx)
    }

    fn call(&mut self, request: Request<ReqBody>) -> Self::Future {
        let method = extract_grpc_method(request.uri().path());
        let client = extract_client_name(&request);
        let caller_tag = extract_caller_tag(&request);
        gauge!("grpc_server_requests_in_flight", "method" => method.clone(), "client" => client.clone())
            .increment(1.0);

        let start = Instant::now();
        // Call inner inside all scopes so any synchronous work in call()
        // sees CLIENT_NAME, CALLER_TAG, and METHOD_NAME.
        let inner = CLIENT_NAME.sync_scope(client.clone(), || {
            CALLER_TAG.sync_scope(caller_tag.clone(), || {
                METHOD_NAME.sync_scope(method.clone(), || self.inner.call(request))
            })
        });

        GrpcMetricsFuture {
            inner: CLIENT_NAME.scope(
                client.clone(),
                CALLER_TAG.scope(caller_tag, METHOD_NAME.scope(method.clone(), inner)),
            ),
            method,
            client,
            start,
            emit_processing_time_header: self.emit_processing_time_header,
        }
    }
}

/// Future returned by [`GrpcMetricsService`].
///
/// Wraps the inner service future with task-local client name, caller tag,
/// and method name propagation, and records request metrics (counter,
/// histogram, in-flight gauge) on completion or cancellation. Lives inline
/// in the caller's async state machine — no heap allocation or dynamic dispatch.
#[pin_project(PinnedDrop)]
#[allow(clippy::type_complexity)]
pub struct GrpcMetricsFuture<F> {
    #[pin]
    inner: TaskLocalFuture<Arc<str>, TaskLocalFuture<Arc<str>, TaskLocalFuture<Arc<str>, F>>>,
    method: Arc<str>,
    client: Arc<str>,
    start: Instant,
    emit_processing_time_header: bool,
}

impl<F, ResBody, E> Future for GrpcMetricsFuture<F>
where
    F: Future<Output = Result<Response<ResBody>, E>>,
{
    type Output = F::Output;

    fn poll(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Self::Output> {
        let this = self.project();
        match this.inner.poll(cx) {
            Poll::Ready(mut result) => {
                let duration_ms = this.start.elapsed().as_secs_f64() * 1000.0;
                counter!("grpc_server_requests_total",
                    "method" => this.method.clone(),
                    "client" => this.client.clone())
                .increment(1);
                histogram!("grpc_server_request_duration_ms",
                    "method" => this.method.clone(),
                    "client" => this.client.clone())
                .record(duration_ms);

                if *this.emit_processing_time_header {
                    if let Ok(ref mut response) = result {
                        if let Ok(hv) = HeaderValue::from_str(&format!("{duration_ms:.3}")) {
                            response.headers_mut().insert(PROCESSING_TIME_HEADER, hv);
                        }
                    }
                }

                Poll::Ready(result)
            }
            Poll::Pending => Poll::Pending,
        }
    }
}

/// Decrement the in-flight gauge when the future is dropped (on both
/// normal completion and cancellation), matching the original
/// `InFlightGuard` behavior.
#[pinned_drop]
impl<F> PinnedDrop for GrpcMetricsFuture<F> {
    fn drop(self: Pin<&mut Self>) {
        let this = self.project();
        gauge!("grpc_server_requests_in_flight",
            "method" => this.method.clone(),
            "client" => this.client.clone())
        .decrement(1.0);
    }
}

/// Extract the gRPC method name from the URI path.
///
/// gRPC paths look like: `/package.Service/MethodName`
/// We extract just the method name part for cleaner metrics.
///
/// Cardinality is bounded because tonic rejects requests to unknown methods
/// before they reach this middleware.
fn extract_grpc_method(path: &str) -> Arc<str> {
    path.rsplit_once('/')
        .map(|(_, method)| method)
        .filter(|m| !m.is_empty())
        .unwrap_or("unknown")
        .into()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_method_from_grpc_path() {
        assert_eq!(
            &*extract_grpc_method("/package.Service/GetPerson"),
            "GetPerson"
        );
        assert_eq!(&*extract_grpc_method("/a.b.c/Method"), "Method");
        assert_eq!(&*extract_grpc_method("/"), "unknown");
        assert_eq!(&*extract_grpc_method(""), "unknown");
    }

    #[test]
    fn extract_caller_tag_from_headers() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", "api/feature-flags")
            .body(())
            .unwrap();
        assert_eq!(&*extract_caller_tag(&req), "api/feature-flags");
    }

    #[test]
    fn extract_caller_tag_defaults_to_unknown() {
        let req = Request::builder().uri("/pkg.Svc/Method").body(()).unwrap();
        assert_eq!(&*extract_caller_tag(&req), "unknown");
    }

    #[test]
    fn extract_caller_tag_treats_empty_as_unknown() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", "")
            .body(())
            .unwrap();
        assert_eq!(&*extract_caller_tag(&req), "unknown");
    }

    #[test]
    fn current_caller_tag_defaults_outside_scope() {
        assert_eq!(&*current_caller_tag(), "unknown");
    }

    #[test]
    fn extract_caller_tag_truncates_long_value() {
        let long_tag = "a".repeat(200);
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", &long_tag)
            .body(())
            .unwrap();
        assert_eq!(extract_caller_tag(&req).len(), MAX_HEADER_TAG_LEN);
    }

    #[test]
    fn extract_caller_tag_rejects_unsafe_chars() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-caller-tag", "bad tag with spaces!")
            .body(())
            .unwrap();
        assert_eq!(&*extract_caller_tag(&req), "unknown");
    }

    #[test]
    fn extract_client_name_truncates_long_value() {
        let long_name = "b".repeat(200);
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-client-name", &long_name)
            .body(())
            .unwrap();
        assert_eq!(extract_client_name(&req).len(), MAX_HEADER_TAG_LEN);
    }

    #[test]
    fn extract_client_name_rejects_unsafe_chars() {
        let req = Request::builder()
            .uri("/pkg.Svc/Method")
            .header("x-client-name", "bad name!")
            .body(())
            .unwrap();
        assert_eq!(&*extract_client_name(&req), "unknown");
    }

    #[test]
    fn sanitize_allows_valid_tag_chars() {
        assert_eq!(
            sanitize_header_tag("api/feature-flags"),
            "api/feature-flags"
        );
        assert_eq!(
            sanitize_header_tag("celery/calculate_cohort_ch"),
            "celery/calculate_cohort_ch"
        );
        assert_eq!(
            sanitize_header_tag("posthog-django-web"),
            "posthog-django-web"
        );
        assert_eq!(sanitize_header_tag("some:tag.v1"), "some:tag.v1");
    }
}
