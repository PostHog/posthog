use axum::Router;

use config::Config;
use envconfig::Envconfig;

use eyre::Result;

mod config;
mod handlers;
mod metrics;

async fn listen(app: Router, bind: String) -> Result<()> {
    let listener = tokio::net::TcpListener::bind(bind).await?;

    axum::serve(listener, app).await?;

    Ok(())
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let app = handlers::router();

    let config = Config::init_from_env().expect("failed to load configuration from env");

    match listen(app, config.bind()).await {
        Ok(_) => {}
        Err(e) => tracing::error!("failed to start hook-producer http server, {}", e),
    }
}
