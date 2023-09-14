use std::future::ready;
use std::sync::Arc;

use axum::{
    routing::{get, post},
    Router,
};
use tower_http::trace::TraceLayer;

use crate::{capture, sink, time::TimeSource};

use crate::prometheus::{setup_metrics_recorder, track_metrics};

#[derive(Clone)]
pub struct State {
    pub sink: Arc<dyn sink::EventSink + Send + Sync>,
    pub timesource: Arc<dyn TimeSource + Send + Sync>,
}

async fn index() -> &'static str {
    "capture"
}

pub fn router<
    TZ: TimeSource + Send + Sync + 'static,
    S: sink::EventSink + Send + Sync + 'static,
>(
    timesource: TZ,
    sink: S,
    metrics: bool,
) -> Router {
    let state = State {
        sink: Arc::new(sink),
        timesource: Arc::new(timesource),
    };

    let router = Router::new()
        // TODO: use NormalizePathLayer::trim_trailing_slash
        .route("/", get(index))
        .route("/i/v0/e", post(capture::event))
        .route("/i/v0/e/", post(capture::event))
        .layer(TraceLayer::new_for_http())
        .layer(axum::middleware::from_fn(track_metrics))
        .with_state(state);

    // Don't install metrics unless asked to
    // Installing a global recorder when capture is used as a library (during tests etc)
    // does not work well.
    if metrics {
        let recorder_handle = setup_metrics_recorder();

        router.route("/metrics", get(move || ready(recorder_handle.render())))
    } else {
        router
    }
}
