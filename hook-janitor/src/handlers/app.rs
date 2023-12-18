use axum::{routing, Router};
use metrics_exporter_prometheus::PrometheusHandle;

use hook_common::metrics;

pub fn app(metrics: Option<PrometheusHandle>) -> Router {
    Router::new()
        .route("/", routing::get(index))
        .route(
            "/metrics",
            routing::get(move || match metrics {
                Some(ref recorder_handle) => std::future::ready(recorder_handle.render()),
                None => std::future::ready("no metrics recorder installed".to_owned()),
            }),
        )
        .layer(axum::middleware::from_fn(metrics::track_metrics))
}

pub async fn index() -> &'static str {
    "rusty-hook janitor"
}
