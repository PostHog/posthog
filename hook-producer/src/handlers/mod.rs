use axum::{routing, Router};

mod index;

pub fn router() -> Router {
    let recorder_handle = crate::metrics::setup_metrics_recorder();

    Router::new()
        .route("/", routing::get(index::get))
        .route(
            "/metrics",
            routing::get(move || std::future::ready(recorder_handle.render())),
        )
        .layer(axum::middleware::from_fn(crate::metrics::track_metrics))
}
