use axum::Router;
use eyre::Result;
mod handlers;

async fn listen(app: Router) -> Result<()> {
    let listener = tokio::net::TcpListener::bind("0.0.0.0:8000").await?;
    axum::serve(listener, app).await?;

    Ok(())
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let app = handlers::router();

    match listen(app).await {
        Ok(_) => {},
        Err(e) => tracing::error!("failed to start hook-producer http server, {}", e)
    }
}
