use envconfig::Envconfig;
use std::net::SocketAddr;
use std::sync::Arc;

use capture::{billing_limits::BillingLimiter, redis::RedisClient, router, sink};
use time::Duration;
use tokio::signal;

#[derive(Envconfig)]
struct Config {
    #[envconfig(default = "false")]
    print_sink: bool,
    #[envconfig(default = "127.0.0.1:3000")]
    address: SocketAddr,
    redis_url: String,
    kafka_hosts: String,
    kafka_topic: String,
}

async fn shutdown() {
    let mut term = signal::unix::signal(signal::unix::SignalKind::terminate())
        .expect("failed to register SIGTERM handler");

    let mut interrupt = signal::unix::signal(signal::unix::SignalKind::interrupt())
        .expect("failed to register SIGINT handler");

    tokio::select! {
        _ = term.recv() => {},
        _ = interrupt.recv() => {},
    };

    tracing::info!("Shutting down gracefully...");
}

#[tokio::main]
async fn main() {
    let config = Config::init_from_env().expect("Invalid configuration:");

    let redis_client =
        Arc::new(RedisClient::new(config.redis_url).expect("failed to create redis client"));

    let billing = BillingLimiter::new(Duration::seconds(5), redis_client.clone())
        .expect("failed to create billing limiter");

    let app = if config.print_sink {
        router::router(
            capture::time::SystemTime {},
            sink::PrintSink {},
            redis_client,
            billing,
            true,
        )
    } else {
        let sink = sink::KafkaSink::new(config.kafka_topic, config.kafka_hosts).unwrap();

        router::router(
            capture::time::SystemTime {},
            sink,
            redis_client,
            billing,
            true,
        )
    };

    // initialize tracing
    tracing_subscriber::fmt::init();

    // run our app with hyper
    // `axum::Server` is a re-export of `hyper::Server`

    tracing::info!("listening on {}", config.address);

    axum::Server::bind(&config.address)
        .serve(app.into_make_service_with_connect_info::<SocketAddr>())
        .with_graceful_shutdown(shutdown())
        .await
        .unwrap();
}
