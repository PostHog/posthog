use std::env;
use std::net::SocketAddr;
use std::sync::Arc;

use capture::{billing_limits::BillingLimiter, redis::RedisClient, router, sink};
use time::Duration;
use tokio::signal;

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
    let use_print_sink = env::var("PRINT_SINK").is_ok();
    let address = env::var("ADDRESS").unwrap_or(String::from("127.0.0.1:3000"));
    let redis_addr = env::var("REDIS").expect("redis required; please set the REDIS env var");

    let redis_client =
        Arc::new(RedisClient::new(redis_addr).expect("failed to create redis client"));

    let billing = BillingLimiter::new(Duration::seconds(5), redis_client.clone())
        .expect("failed to create billing limiter");

    let app = if use_print_sink {
        router::router(
            capture::time::SystemTime {},
            sink::PrintSink {},
            redis_client,
            billing,
            true,
        )
    } else {
        let brokers = env::var("KAFKA_BROKERS").expect("Expected KAFKA_BROKERS");
        let topic = env::var("KAFKA_TOPIC").expect("Expected KAFKA_TOPIC");

        let sink = sink::KafkaSink::new(topic, brokers).unwrap();

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

    tracing::info!("listening on {}", address);

    axum::Server::bind(&address.parse().unwrap())
        .serve(app.into_make_service_with_connect_info::<SocketAddr>())
        .with_graceful_shutdown(shutdown())
        .await
        .unwrap();
}
