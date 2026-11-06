use axum::body::Body;
use axum::extract::{Path, RawQuery, State};
use axum::http::{header, StatusCode};
use axum::response::Response;

use crate::api::ApiError;
use crate::state::AppState;

/// The wildcard path is interpolated into the upstream URL; dot segments —
/// including percent-encoded ones, which URL parsers decode and normalize —
/// could otherwise escape the `/debug/` prefix and reach other endpoints on
/// the pod. Debug API paths only ever use simple names, so enforce a strict
/// character allowlist instead of chasing encodings.
fn is_safe_debug_path(rest: &str) -> bool {
    !rest.is_empty()
        && rest.split('/').all(|segment| {
            !segment.is_empty()
                && !segment.starts_with('.')
                && segment
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.')
        })
}

fn build_upstream_url(target: &str, rest: &str, query: Option<&str>) -> String {
    match query {
        Some(query) => format!("http://{target}/debug/{rest}?{query}"),
        None => format!("http://{target}/debug/{rest}"),
    }
}

/// Proxy `GET /pods/:namespace/:name/debug/<rest>` to the pod's debug API.
/// The upstream body is piped through as a byte stream, which also carries
/// SSE (`/debug/events`) without buffering.
pub async fn proxy_debug(
    State(state): State<AppState>,
    Path((namespace, name, rest)): Path<(String, String, String)>,
    RawQuery(query): RawQuery,
) -> Result<Response, ApiError> {
    if !is_safe_debug_path(&rest) {
        return Err(ApiError::bad_request("invalid debug path"));
    }

    let target = state
        .pods
        .resolve_proxy_target(&state.config, &namespace, &name)
        .await
        .map_err(|e| ApiError::unavailable(format!("pod discovery unavailable: {e:#}")))?
        .ok_or_else(|| ApiError::not_found(format!("no matching pod '{namespace}/{name}'")))?;

    let url = build_upstream_url(&target, &rest, query.as_deref());
    let mut request = state.http.get(&url);
    // The consumer's debug API fails closed: every request must carry the
    // shared per-hop secret. Attached here — never forwarded from the browser —
    // so the control plane is the trust boundary for its clients.
    if let Some(secret) = state
        .config
        .debug_api_secret
        .as_deref()
        .filter(|s| !s.is_empty())
    {
        request = request.header("X-Debug-Api-Secret", secret);
    }
    let upstream = request
        .send()
        .await
        .map_err(|e| ApiError::upstream(format!("debug API request to '{name}' failed: {e}")))?;

    let status =
        StatusCode::from_u16(upstream.status().as_u16()).unwrap_or(StatusCode::BAD_GATEWAY);
    let mut builder = Response::builder()
        .status(status)
        .header(header::CACHE_CONTROL, "no-cache");
    if let Some(content_type) = upstream.headers().get(header::CONTENT_TYPE) {
        builder = builder.header(header::CONTENT_TYPE, content_type);
    }
    builder
        .body(Body::from_stream(upstream.bytes_stream()))
        .map_err(|e| ApiError::upstream(format!("failed to build proxy response: {e}")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_dot_segments_encodings_and_empty_paths() {
        assert!(is_safe_debug_path("state"));
        assert!(is_safe_debug_path("events"));
        assert!(is_safe_debug_path("some/nested/path-1_2.json"));
        assert!(!is_safe_debug_path(""));
        assert!(!is_safe_debug_path(".."));
        assert!(!is_safe_debug_path("../metrics"));
        assert!(!is_safe_debug_path("state/../../admin"));
        assert!(!is_safe_debug_path("./state"));
        assert!(!is_safe_debug_path("..\\metrics"));
        // Percent-encoded dot segments (single- or double-encoded) would be
        // normalized out of /debug/ by the upstream URL parser.
        assert!(!is_safe_debug_path("%2e%2e/metrics"));
        assert!(!is_safe_debug_path("%252e%252e/metrics"));
        assert!(!is_safe_debug_path("state//admin"));
    }

    #[test]
    fn forwards_query_string() {
        assert_eq!(
            build_upstream_url("10.0.0.7:3301", "events", Some("limit=10")),
            "http://10.0.0.7:3301/debug/events?limit=10"
        );
        assert_eq!(
            build_upstream_url("10.0.0.7:3301", "state", None),
            "http://10.0.0.7:3301/debug/state"
        );
    }
}
