use axum::{routing, Router};

pub fn app() -> Router {
    Router::new().route("/", routing::get(index))
}

pub async fn index() -> &'static str {
    "rusty-hook janitor"
}
