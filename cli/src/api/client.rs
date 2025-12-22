use std::{
    fmt::Display,
    sync::{Arc, Mutex},
    time::Duration,
};

use anyhow::Result;
use reqwest::{
    blocking::{Client, RequestBuilder, Response},
    header::{HeaderMap, HeaderValue},
    Method, Url,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::debug;

use crate::{invocation_context::InvocationConfig, utils::throttler::Throttler};
const ONE_MINUTE_IN_MS: u64 = 60 * 1000;

#[derive(Clone)]
pub struct PHClient {
    config: InvocationConfig,
    client: Client,
    throttler: Arc<Mutex<Throttler>>,
}

#[derive(Error, Debug)]
pub enum ClientError {
    RequestError(reqwest::Error),
    // All invalid status codes
    ApiError(u16, Box<Url>, String),
    InvalidUrl(String),
}

impl Display for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientError::RequestError(err) => write!(f, "Request error: {err}"),
            ClientError::InvalidUrl(msg) => {
                write!(f, "Failed to build URL: {msg}")
            }
            ClientError::ApiError(status, url, body) => {
                // We only parse api error on display to catch all errors even when the body is not JSON
                match serde_json::from_str::<ApiErrorResponse>(body) {
                    Ok(api_error) => {
                        write!(f, "API error: {api_error}")
                    }
                    Err(_) => write!(
                        f,
                        "API error: status='{status}' url='{url}' message='{body}'",
                    ),
                }
            }
        }
    }
}

impl From<reqwest::Error> for ClientError {
    fn from(error: reqwest::Error) -> Self {
        ClientError::RequestError(error)
    }
}

#[derive(Serialize, Deserialize, Debug)]
pub struct ApiErrorResponse {
    r#type: String,
    code: String,
    detail: String,
    attr: Option<String>,
}

impl Display for ApiErrorResponse {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "error='{}' code='{}' details='{}'",
            self.r#type, self.code, self.detail
        )?;
        if let Some(attr) = &self.attr {
            write!(f, ", attributes='{attr}'")?;
        }
        Ok(())
    }
}

pub trait SendRequestFn: FnOnce(RequestBuilder) -> RequestBuilder {}

impl PHClient {
    pub fn from_config(config: InvocationConfig) -> anyhow::Result<Self> {
        let client = Self::build_client(config.skip_ssl)?;
        let throttler = Arc::new(Mutex::new(Throttler::new(
            config.rate_limit,
            Duration::from_millis(ONE_MINUTE_IN_MS),
        )));
        Ok(Self {
            config,
            client,
            throttler,
        })
    }

    pub fn get(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::GET, url)
    }

    pub fn post(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::POST, url)
    }

    pub fn put(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::PUT, url)
    }

    pub fn delete(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::DELETE, url)
    }

    pub fn patch(&self, url: Url) -> RequestBuilder {
        self.create_request(Method::PATCH, url)
    }

    pub fn send_get<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::GET, url, builder)
    }

    pub fn send_post<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::POST, url, builder)
    }

    pub fn send_delete<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::DELETE, url, builder)
    }

    pub fn send_put<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::PUT, url, builder)
    }

    pub fn send_request<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        method: Method,
        url: Url,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.throttler.lock().unwrap().throttle();
        let request = builder(self.create_request(method, url));
        match request.send() {
            Ok(response) => {
                if response.status().is_success() {
                    Ok(response)
                } else {
                    let status = response.status().as_u16();
                    let box_url = Box::new(response.url().clone());
                    let body = response.text()?;
                    Err(ClientError::ApiError(status, box_url, body))
                }
            }
            Err(err) => Err(ClientError::from(err)),
        }
    }

    pub fn get_env_id(&self) -> &String {
        &self.config.env_id
    }

    fn create_request(&self, method: Method, url: Url) -> RequestBuilder {
        let headers = self.build_headers();
        debug!("building request for {method} {url}");
        self.client
            .request(method, url)
            .bearer_auth(&self.config.api_key)
            .headers(headers)
    }

    fn build_client(skip_ssl: bool) -> anyhow::Result<Client> {
        let client = Client::builder()
            .danger_accept_invalid_certs(skip_ssl)
            .build()?;
        Ok(client)
    }

    fn build_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("Content-Type", HeaderValue::from_static("application/json"));
        headers.insert("User-Agent", HeaderValue::from_static("posthog-cli"));
        headers
    }

    pub fn env_url(&self, path: &str) -> Result<Url, ClientError> {
        self.build_url("environments", path)
    }

    pub fn project_url(&self, path: &str) -> Result<Url, ClientError> {
        self.build_url("projects", path)
    }

    fn build_url(&self, base: &str, path: &str) -> Result<Url, ClientError> {
        let host = self.config.host.clone();
        let env_id = self.config.env_id.clone();

        let base_url = Url::parse(&host)
            .map_err(|e| ClientError::InvalidUrl(format!("{e} {host}")))?
            .join(&format!("api/{base}/{env_id}/"))
            .map_err(|e| ClientError::InvalidUrl(format!("{e} {host}/api/{base}/{env_id}")))?
            .join(path)
            .map_err(|e| {
                ClientError::InvalidUrl(format!("{e} {host}/api/{base}/{env_id}/{path}"))
            })?;
        Ok(base_url)
    }
}
