use axum::Router;
use config::Config;
use envconfig::Envconfig;
use eyre::Result;

use hook_common::metrics::setup_metrics_routes;
use hook_common::pgqueue::PgQueue;

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
        // TODO: Coupling the queue name to the PgQueue object doesn't seem ideal from the api
        // side, but we don't need more than one queue for now.
        &config.queue_name,
        &config.database_url,
    )
    .await
    .expect("failed to initialize queue");

    let app = handlers::add_routes(Router::new(), pg_queue);
    let app = setup_metrics_routes(app);

    match listen(app, config.bind()).await {
        Ok(_) => {}
        Err(e) => tracing::error!("failed to start hook-api http server, {}", e),
    }
}
