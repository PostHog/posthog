use axum::Router;
use config::Config;
use envconfig::Envconfig;
use eyre::Result;

use hook_common::metrics;
use hook_common::pgqueue::{PgQueue, RetryPolicy};

mod config;
mod handlers;

async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let config = Config::init_from_env().expect("failed to load configuration from env");

    let pg_queue = PgQueue::new(
        // TODO: Coupling the queue name to the PgQueue object doesn't seem ideal from the producer
        // side, but we don't need more than one queue for now.
        &config.queue_name,
        &config.table_name,
        &config.database_url,
        // TODO: It seems unnecessary that the producer side needs to know about the retry policy.
        RetryPolicy::default(),
    )
    .await
    .expect("failed to initialize queue");

    let recorder_handle = metrics::setup_metrics_recorder();

    let app = handlers::app(pg_queue, Some(recorder_handle));

    match listen(app, config.bind()).await {
        Ok(_) => {}
        Err(e) => tracing::error!("failed to start hook-producer http server, {}", e),
    }
}
