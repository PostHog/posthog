use axum::{routing, Router};

mod index;

pub fn router() -> Router {
    let app = Router::new().route("/", routing::get(index::get));

    app
}
