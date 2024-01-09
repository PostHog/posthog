use std::time::Instant;

use axum::{extract::State, http::StatusCode, Json};
use hook_common::webhook::{WebhookJobMetadata, WebhookJobParameters};
use serde_derive::Deserialize;
use url::Url;

use hook_common::pgqueue::{NewJob, PgQueue};
use serde::Serialize;
use tracing::{debug, error};

const MAX_BODY_SIZE: usize = 1_000_000;

#[derive(Serialize, Deserialize)]
pub struct WebhookPostResponse {
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

/// The body of a request made to create a webhook Job.
#[derive(Deserialize, Serialize, Debug, PartialEq, Clone)]
pub struct WebhookPostRequestBody {
    parameters: WebhookJobParameters,
    metadata: WebhookJobMetadata,

    #[serde(default = "default_max_attempts")]
    max_attempts: u32,
}

fn default_max_attempts() -> u32 {
    3
}

pub async fn post(
    State(pg_queue): State<PgQueue>,
    Json(payload): Json<WebhookPostRequestBody>,
) -> Result<Json<WebhookPostResponse>, (StatusCode, Json<WebhookPostResponse>)> {
    debug!("received payload: {:?}", payload);

    if payload.parameters.body.len() > MAX_BODY_SIZE {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(WebhookPostResponse {
                error: Some("body too large".to_owned()),
            }),
        ));
    }

    let url_hostname = get_hostname(&payload.parameters.url)?;
    // We could cast to i32, but this ensures we are not wrapping.
    let max_attempts = i32::try_from(payload.max_attempts).map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(WebhookPostResponse {
                error: Some("invalid number of max attempts".to_owned()),
            }),
        )
    })?;
    let job = NewJob::new(
        max_attempts,
        payload.metadata,
        payload.parameters,
        url_hostname.as_str(),
    );

    let start_time = Instant::now();

    pg_queue.enqueue(job).await.map_err(internal_error)?;

    let elapsed_time = start_time.elapsed().as_secs_f64();
    metrics::histogram!("webhook_producer_enqueue").record(elapsed_time);

    Ok(Json(WebhookPostResponse { error: None }))
}

fn internal_error<E>(err: E) -> (StatusCode, Json<WebhookPostResponse>)
where
    E: std::error::Error,
{
    error!("internal error: {}", err);
    (
        StatusCode::INTERNAL_SERVER_ERROR,
        Json(WebhookPostResponse {
            error: Some(err.to_string()),
        }),
    )
}

fn get_hostname(url_str: &str) -> Result<String, (StatusCode, Json<WebhookPostResponse>)> {
    let url = Url::parse(url_str).map_err(|_| {
        (
            StatusCode::BAD_REQUEST,
            Json(WebhookPostResponse {
                error: Some("could not parse url".to_owned()),
            }),
        )
    })?;

    match url.host_str() {
        Some(hostname) => Ok(hostname.to_owned()),
        None => Err((
            StatusCode::BAD_REQUEST,
            Json(WebhookPostResponse {
                error: Some("couldn't extract hostname from url".to_owned()),
            }),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use axum::{
        body::Body,
        http::{self, Request, StatusCode},
        Router,
    };
    use hook_common::pgqueue::PgQueue;
    use hook_common::webhook::{HttpMethod, WebhookJobParameters};
    use http_body_util::BodyExt;
    use sqlx::PgPool; // for `collect`
    use std::collections;
    use tower::ServiceExt; // for `call`, `oneshot`, and `ready`

    use crate::handlers::app::add_routes;

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_success(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db)
            .await
            .expect("failed to construct pg_queue");

        let app = add_routes(Router::new(), pg_queue);

        let mut headers = collections::HashMap::new();
        headers.insert("Content-Type".to_owned(), "application/json".to_owned());
        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        serde_json::to_string(&WebhookPostRequestBody {
                            parameters: WebhookJobParameters {
                                headers,
                                method: HttpMethod::POST,
                                url: "http://example.com/".to_owned(),
                                body: r#"{"a": "b"}"#.to_owned(),
                            },
                            metadata: WebhookJobMetadata {
                                team_id: 1,
                                plugin_id: 2,
                                plugin_config_id: 3,
                            },
                            max_attempts: 1,
                        })
                        .unwrap(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::OK);

        let body = response.into_body().collect().await.unwrap().to_bytes();
        assert_eq!(&body[..], b"{}");
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_bad_url(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db)
            .await
            .expect("failed to construct pg_queue");

        let app = add_routes(Router::new(), pg_queue);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        serde_json::to_string(&WebhookPostRequestBody {
                            parameters: WebhookJobParameters {
                                headers: collections::HashMap::new(),
                                method: HttpMethod::POST,
                                url: "invalid".to_owned(),
                                body: r#"{"a": "b"}"#.to_owned(),
                            },
                            metadata: WebhookJobMetadata {
                                team_id: 1,
                                plugin_id: 2,
                                plugin_config_id: 3,
                            },
                            max_attempts: 1,
                        })
                        .unwrap(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_payload_missing_fields(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db)
            .await
            .expect("failed to construct pg_queue");

        let app = add_routes(Router::new(), pg_queue);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body("{}".to_owned())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_payload_not_json(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db)
            .await
            .expect("failed to construct pg_queue");

        let app = add_routes(Router::new(), pg_queue);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body("x".to_owned())
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }

    #[sqlx::test(migrations = "../migrations")]
    async fn webhook_payload_body_too_large(db: PgPool) {
        let pg_queue = PgQueue::new_from_pool("test_index", db)
            .await
            .expect("failed to construct pg_queue");

        let app = add_routes(Router::new(), pg_queue);

        let bytes: Vec<u8> = vec![b'a'; 1_000_000 * 2];
        let long_string = String::from_utf8_lossy(&bytes);

        let response = app
            .oneshot(
                Request::builder()
                    .method(http::Method::POST)
                    .uri("/webhook")
                    .header(http::header::CONTENT_TYPE, "application/json")
                    .body(Body::from(
                        serde_json::to_string(&WebhookPostRequestBody {
                            parameters: WebhookJobParameters {
                                headers: collections::HashMap::new(),
                                method: HttpMethod::POST,
                                url: "http://example.com".to_owned(),
                                body: long_string.to_string(),
                            },
                            metadata: WebhookJobMetadata {
                                team_id: 1,
                                plugin_id: 2,
                                plugin_config_id: 3,
                            },
                            max_attempts: 1,
                        })
                        .unwrap(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap();

        assert_eq!(response.status(), StatusCode::BAD_REQUEST);
    }
}
