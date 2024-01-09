use std::time::Instant;

use axum::{
    body::Body, extract::MatchedPath, http::Request, middleware::Next, response::IntoResponse,
    routing::get, Router,
};
use metrics_exporter_prometheus::{PrometheusBuilder, PrometheusHandle};

/// Bind a `TcpListener` on the provided bind address to serve a `Router` on it.
/// This function is intended to take a Router as returned by `setup_metrics_router`, potentially with more routes added by the caller.
pub async fn serve(router: Router, bind: &str) -> Result<(), std::io::Error> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, router).await?;

    Ok(())
}

/// Build a Router for a metrics endpoint.
pub fn setup_metrics_router() -> Router {
    let recorder_handle = setup_metrics_recorder();

    Router::new()
        .route(
            "/metrics",
            get(move || std::future::ready(recorder_handle.render())),
        )
        .layer(axum::middleware::from_fn(track_metrics))
}

pub fn setup_metrics_recorder() -> PrometheusHandle {
    const EXPONENTIAL_SECONDS: &[f64] = &[
        0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
    ];

    PrometheusBuilder::new()
        .set_buckets(EXPONENTIAL_SECONDS)
        .unwrap()
        .install_recorder()
        .unwrap()
}

/// Middleware to record some common HTTP metrics
/// Someday tower-http might provide a metrics middleware: https://github.com/tower-rs/tower-http/issues/57
pub async fn track_metrics(req: Request<Body>, next: Next) -> impl IntoResponse {
    let start = Instant::now();

    let path = if let Some(matched_path) = req.extensions().get::<MatchedPath>() {
        matched_path.as_str().to_owned()
    } else {
        req.uri().path().to_owned()
    };

    let method = req.method().clone();

    // Run the rest of the request handling first, so we can measure it and get response
    // codes.
    let response = next.run(req).await;

    let latency = start.elapsed().as_secs_f64();
    let status = response.status().as_u16().to_string();

    let labels = [
        ("method", method.to_string()),
        ("path", path),
        ("status", status),
    ];

    metrics::counter!("http_requests_total", &labels).increment(1);
    metrics::histogram!("http_requests_duration_seconds", &labels).record(latency);

    response
}
