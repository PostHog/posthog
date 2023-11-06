use std::net::TcpListener;

use envconfig::Envconfig;
use tokio::signal;

use capture::config::Config;
use capture::server::serve;

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
    // initialize tracing
    tracing_subscriber::fmt::init();

    let config = Config::init_from_env().expect("Invalid configuration:");
    let listener = TcpListener::bind(config.address).unwrap();
    serve(config, listener, shutdown()).await
}
