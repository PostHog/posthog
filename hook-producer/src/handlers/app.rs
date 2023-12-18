use axum::{routing, Router};
use metrics_exporter_prometheus::PrometheusHandle;

use hook_common::metrics;
use hook_common::pgqueue::PgQueue;

use super::webhook;

pub fn app(pg_pool: PgQueue, metrics: Option<PrometheusHandle>) -> Router {
    Router::new()
        .route("/", routing::get(index))
        .route(
            "/metrics",
            routing::get(move || match metrics {
                Some(ref recorder_handle) => std::future::ready(recorder_handle.render()),
                None => std::future::ready("no metrics recorder installed".to_owned()),
            }),
        )
        .route("/webhook", routing::post(webhook::post).with_state(pg_pool))
        .layer(axum::middleware::from_fn(metrics::track_metrics))
}

pub async fn index() -> &'static str {
    "rusty-hook producer"
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{
        body::Body,
        http::{Request, StatusCode},
    };
    use hook_common::pgqueue::{PgQueue, RetryPolicy};
    use http_body_util::BodyExt; // for `collect`
    use tower::ServiceExt; // for `call`, `oneshot`, and `ready`

    #[tokio::test]
    async fn index() {
        let pg_queue = PgQueue::new(
            "test_index",
            "job_queue",
            "postgres://posthog:posthog@localhost:15432/test_database",
            RetryPolicy::default(),
        )
        .await
        .expect("failed to construct pg_queue");

        let app = app(pg_queue, None);

        let response = app
            .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);

        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&body[..], b"rusty-hook producer");
    }
}
