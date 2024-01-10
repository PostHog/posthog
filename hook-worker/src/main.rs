//! Consume `PgQueue` jobs to run webhook calls.
use envconfig::Envconfig;

use hook_common::{
    metrics::serve, metrics::setup_metrics_router, pgqueue::PgQueue, retry::RetryPolicy,
};
use hook_worker::config::Config;
use hook_worker::error::WorkerError;
use hook_worker::worker::WebhookWorker;

#[tokio::main]
async fn main() -> Result<(), WorkerError> {
    tracing_subscriber::fmt::init();

    let config = Config::init_from_env().expect("Invalid configuration:");

    let retry_policy = RetryPolicy::build(
        config.retry_policy.backoff_coefficient,
        config.retry_policy.initial_interval.0,
    )
    .maximum_interval(config.retry_policy.maximum_interval.0)
    .queue(&config.retry_policy.retry_queue_name)
    .provide();
    let queue = PgQueue::new(&config.queue_name, &config.database_url)
        .await
        .expect("failed to initialize queue");

    let worker = WebhookWorker::new(
        &config.worker_name,
        &queue,
        config.poll_interval.0,
        config.request_timeout.0,
        config.max_concurrent_jobs,
        retry_policy,
    );

    let bind = config.bind();
    tokio::task::spawn(async move {
        let router = setup_metrics_router();
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    });

    worker.run(config.transactional).await?;

    Ok(())
}
