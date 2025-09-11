//! Consume `PgQueue` jobs to run webhook calls.
use axum::routing::get;
use axum::Router;
use envconfig::Envconfig;
use hook_common::pgqueue::PgQueue;
use hook_common::retry::RetryPolicy;
use std::future::ready;

use common_kafka::kafka_producer::create_kafka_producer;
use common_metrics::{serve, setup_metrics_routes};
use health::HealthRegistry;
use hook_worker::config::Config;
use hook_worker::error::WorkerError;
use hook_worker::worker::WebhookWorker;

common_alloc::used!();

#[tokio::main]
async fn main() -> Result<(), WorkerError> {
    tracing_subscriber::fmt::init();

    let config = Config::init_from_env().expect("Invalid configuration:");

    let liveness = HealthRegistry::new("liveness");
    let worker_liveness = liveness
        .register("worker".to_string(), time::Duration::seconds(60)) // TODO: compute the value from worker params
        .await;

    let mut retry_policy_builder = RetryPolicy::build(
        config.retry_policy.backoff_coefficient,
        config.retry_policy.initial_interval.0,
    )
    .maximum_interval(config.retry_policy.maximum_interval.0);

    retry_policy_builder = if let Some(retry_queue_name) = &config.retry_policy.retry_queue_name {
        retry_policy_builder.queue(retry_queue_name.as_str())
    } else {
        retry_policy_builder
    };

    let queue = PgQueue::new(
        config.queue_name.as_str(),
        &config.database_url,
        config.max_pg_connections,
        "hook-worker",
    )
    .await
    .expect("failed to initialize queue");

    let kafka_liveness = liveness
        .register("rdkafka".to_string(), time::Duration::seconds(30))
        .await;
    let kafka_producer = create_kafka_producer(&config.kafka, kafka_liveness)
        .await
        .expect("failed to create kafka producer");

    let worker = WebhookWorker::new(
        &config.worker_name,
        &queue,
        config.dequeue_batch_size,
        config.poll_interval.0,
        config.request_timeout.0,
        config.max_concurrent_jobs,
        retry_policy_builder.provide(),
        config.allow_internal_ips,
        kafka_producer,
        config.cdp_function_callbacks_topic.to_owned(),
        config.hog_mode,
        worker_liveness,
    );

    let router = Router::new()
        .route("/", get(index))
        .route("/_readiness", get(index))
        .route("/_liveness", get(move || ready(liveness.get_status())));
    let router = setup_metrics_routes(router);
    let bind = config.bind();
    tokio::task::spawn(async move {
        serve(router, &bind)
            .await
            .expect("failed to start serving metrics");
    });

    worker.run().await;

    Ok(())
}

pub async fn index() -> &'static str {
    "rusty-hook worker"
}
