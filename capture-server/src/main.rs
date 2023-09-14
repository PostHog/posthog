use std::env;
use std::net::SocketAddr;

use capture::{router, sink, time};
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

    let app = if use_print_sink {
        router::router(time::SystemTime {}, sink::PrintSink {}, true)
    } else {
        let brokers = env::var("KAFKA_BROKERS").expect("Expected KAFKA_BROKERS");
        let topic = env::var("KAFKA_TOPIC").expect("Expected KAFKA_TOPIC");

        let sink = sink::KafkaSink::new(topic, brokers).unwrap();

        router::router(time::SystemTime {}, sink, true)
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
