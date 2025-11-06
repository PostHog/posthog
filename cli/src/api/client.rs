use std::fmt::Display;

use anyhow::Result;
use reqwest::{
    blocking::{Client, RequestBuilder, Response},
    header::{HeaderMap, HeaderValue},
    Method, Url,
};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tracing::debug;

use crate::invocation_context::InvocationConfig;

#[derive(Clone)]
pub struct PHClient {
    config: InvocationConfig,
    base_url: Url,
    client: Client,
}

#[derive(Error, Debug)]
pub enum ClientError {
    RequestError(reqwest::Error),
    // All invalid status codes
    ApiError(u16, Box<Url>, String),
}

impl Display for ClientError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ClientError::RequestError(err) => write!(f, "Request error: {}", err),
            ClientError::ApiError(status, url, body) => {
                // We only parse api error on display to catch all errors even when the body is not JSON
                match serde_json::from_str::<ApiError>(body) {
                    Ok(api_error) => {
                        write!(
                            f,
                            "API error (type='{}' status='{}' code='{}' details='{}')",
                            api_error.r#type, status, api_error.code, api_error.detail
                        )?;
                        if let Some(attr) = &api_error.attr {
                            write!(f, ", attributes='{}'", attr)?;
                        }
                        Ok(())
                    }
                    Err(_) => write!(
                        f,
                        "API error (status='{}' url='{}' message='{}')",
                        status, url, body
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
pub struct ApiError {
    r#type: String,
    code: String,
    detail: String,
    attr: Option<String>,
}

impl Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "error='{}' code='{}' details='{}'",
            self.r#type, self.code, self.detail
        )?;
        if let Some(attr) = &self.attr {
            write!(f, ", attributes='{}'", attr)?;
        }
        Ok(())
    }
}

pub trait SendRequestFn: FnOnce(RequestBuilder) -> RequestBuilder {}

impl PHClient {
    pub fn from_config(config: InvocationConfig) -> anyhow::Result<Self> {
        let base_url = Self::build_base_url(&config)?;
        let client = Self::build_client(&config)?;
        Ok(Self {
            config,
            base_url,
            client,
        })
    }

    pub fn get(&self, path: &str) -> RequestBuilder {
        self.create_request(Method::GET, path)
    }

    pub fn post(&self, path: &str) -> RequestBuilder {
        self.create_request(Method::POST, path)
    }

    pub fn put(&self, path: &str) -> RequestBuilder {
        self.create_request(Method::PUT, path)
    }

    pub fn delete(&self, path: &str) -> RequestBuilder {
        self.create_request(Method::DELETE, path)
    }

    pub fn patch(&self, path: &str) -> RequestBuilder {
        self.create_request(Method::PATCH, path)
    }

    pub fn send_get<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        path: &str,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::GET, path, builder)
    }

    pub fn send_post<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        path: &str,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::POST, path, builder)
    }

    pub fn send_delete<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        path: &str,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::DELETE, path, builder)
    }

    pub fn send_put<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        path: &str,
        builder: F,
    ) -> Result<Response, ClientError> {
        self.send_request(Method::PUT, path, builder)
    }

    pub fn send_request<F: FnOnce(RequestBuilder) -> RequestBuilder>(
        &self,
        method: Method,
        path: &str,
        builder: F,
    ) -> Result<Response, ClientError> {
        let request = builder(self.create_request(method, path));
        match request.send() {
            Ok(response) => {
                if response.status().is_success() {
                    Ok(response)
                } else {
                    let status = response.status().as_u16();
                    let box_url = Box::new(response.url().clone());
                    let body = response.text()?;
                    Err(ClientError::ApiError(status, box_url, body))
                    // match serde_json::from_str(&body) {
                    //     Ok(err) => Err(ClientError::ApiError(status, box_url, body)),
                    //     Err(_) => Err(ClientError::RawApiError(status, box_url, body)),
                    // }
                }
            }
            Err(err) => Err(ClientError::from(err)),
        }
    }

    pub fn get_env_id(&self) -> &String {
        &self.config.env_id
    }

    fn create_request(&self, method: Method, path: &str) -> RequestBuilder {
        let url = self.build_url(path);
        let headers = self.build_headers();
        debug!("building request for {} {}", method, url);
        self.client
            .request(method, url)
            .bearer_auth(&self.config.api_key)
            .headers(headers)
    }

    fn build_client(config: &InvocationConfig) -> anyhow::Result<Client> {
        let client = Client::builder()
            .danger_accept_invalid_certs(config.skip_ssl)
            .build()?;
        Ok(client)
    }

    fn build_base_url(config: &InvocationConfig) -> anyhow::Result<Url> {
        let base_url = Url::parse(&format!(
            "{}/api/environments/{}/",
            config.host, config.env_id
        ))
        .unwrap();
        Ok(base_url)
    }

    fn build_headers(&self) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert("Content-Type", HeaderValue::from_static("application/json"));
        headers.insert("User-Agent", HeaderValue::from_static("posthog-cli"));
        headers
    }

    fn build_url(&self, path: &str) -> Url {
        self.base_url
            .join(path)
            .unwrap_or_else(|err| panic!("Failed to build URL for path: {err}"))
    }
}
