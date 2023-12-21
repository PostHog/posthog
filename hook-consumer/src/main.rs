use envconfig::Envconfig;

use hook_common::{metrics::serve_metrics, pgqueue::PgQueue, retry::RetryPolicy};
use hook_consumer::config::Config;
use hook_consumer::consumer::WebhookConsumer;
use hook_consumer::error::ConsumerError;

#[tokio::main]
async fn main() -> Result<(), ConsumerError> {
    let config = Config::init_from_env().expect("Invalid configuration:");

    let retry_policy = RetryPolicy::new(
        config.retry_policy.backoff_coefficient,
        config.retry_policy.initial_interval.0,
        Some(config.retry_policy.maximum_interval.0),
    );
    let queue = PgQueue::new(&config.queue_name, &config.table_name, &config.database_url)
        .await
        .expect("failed to initialize queue");

    let consumer = WebhookConsumer::new(
        &config.consumer_name,
        &queue,
        config.poll_interval.0,
        config.request_timeout.0,
        config.max_concurrent_jobs,
        retry_policy,
    );

    let bind = config.bind();
    tokio::task::spawn(async move {
        serve_metrics(&bind)
            .await
            .expect("failed to start serving metrics");
    });

    consumer.run(config.transactional).await?;

    Ok(())
}
