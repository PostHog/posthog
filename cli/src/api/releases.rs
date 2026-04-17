use std::collections::HashMap;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{info, warn};
use uuid::Uuid;

use crate::{
    api::client::{ApiErrorResponse, ClientError},
    invocation_context::context,
    utils::{files::content_hash, git::GitInfo},
};

/// Path segment the `ReleaseViewSet` is mounted under. Used by
/// `is_hash_already_in_use` to avoid matching unrelated endpoints that might
/// coincidentally return a `validation_error` containing "already in use".
const RELEASES_PATH_SEGMENT: &str = "/error_tracking/releases";

#[derive(Debug, Clone, Deserialize)]
pub struct Release {
    pub id: Uuid,
    pub hash_id: String,
    pub version: String,
    pub project: String,
}

#[derive(Debug, Clone, Default)]
pub struct ReleaseBuilder {
    name: Option<String>,
    version: Option<String>,
    metadata: HashMap<String, Value>,
}

// Internal, what we send to the API
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CreateReleaseRequest {
    #[serde(skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,
    pub hash_id: String,
    pub version: String,
    // TODO: update API to use name instead
    pub project: String,
}

impl Release {
    pub fn lookup(name: &str, version: &str) -> Result<Option<Self>, ClientError> {
        let hash_id = content_hash([name, version]);
        let client = &context().client;

        let path = format!("error_tracking/releases/hash/{hash_id}");
        let response = client.send_get(client.project_url(&path)?, |req| req);

        if let Err(err) = response {
            if let ClientError::ApiError(404, _, _) = err {
                warn!("release {}@{} not found", name, version);
                return Ok(None);
            }
            warn!("failed to get release from hash: {}", err);
            Err(err)
        } else {
            info!("found release {}@{}", name, version);
            Ok(Some(response.unwrap().json()?))
        }
    }
}

impl ReleaseBuilder {
    pub fn init_from_git(info: GitInfo) -> Self {
        let mut metadata = HashMap::new();
        metadata.insert(
            "git".to_string(),
            serde_json::to_value(info.clone()).expect("can serialize gitinfo"),
        );

        Self {
            metadata,
            version: Some(info.commit_id), // TODO - We should pull this commits tags and use them if we can
            name: info.repo_name,
        }
    }

    pub fn with_git(&mut self, info: GitInfo) -> &mut Self {
        if !self.has_name() {
            if let Some(name) = &info.repo_name {
                self.with_name(name);
            }
        }
        if !self.has_version() {
            self.with_version(&info.commit_id);
        }
        self.with_metadata("git", info)
            .expect("We can serialise git info")
    }

    pub fn with_metadata<T>(&mut self, key: &str, val: T) -> Result<&mut Self>
    where
        T: Serialize,
    {
        self.metadata
            .insert(key.to_string(), serde_json::to_value(val)?);
        Ok(self)
    }

    pub fn has_name(&self) -> bool {
        self.name.is_some()
    }

    pub fn with_name(&mut self, name: &str) -> &mut Self {
        self.name = Some(name.to_string());
        self
    }

    pub fn has_version(&self) -> bool {
        self.version.is_some()
    }

    pub fn with_version(&mut self, version: &str) -> &mut Self {
        self.version = Some(version.to_string());
        self
    }

    pub fn can_create(&self) -> bool {
        self.version.is_some() && self.name.is_some()
    }

    pub fn missing(&self) -> Vec<&str> {
        let mut missing = Vec::new();

        if self.version.is_none() {
            missing.push("release-version");
        }
        if self.name.is_none() {
            missing.push("release-name");
        }
        missing
    }

    pub fn fetch_or_create(self) -> Result<Release> {
        if !self.can_create() {
            anyhow::bail!(
                "Tried to create a release while missing key fields: {}",
                self.missing().join(", ")
            )
        }
        let version = self.version.as_ref().unwrap();
        let project = self.name.as_ref().unwrap();
        if let Some(release) = Release::lookup(project, version)? {
            Ok(release)
        } else {
            self.create_release()
        }
    }

    pub fn create_release(self) -> Result<Release> {
        // The way to encode this kind of thing in the type system is a thing called "Type-state". It's cool,
        // and if you're reading this and thinking "hmm this feels kind of gross and fragile", you should
        // google "rust type state pattern". The only problem is it's a lot of boilerplate, so I didn't do it.
        if !self.can_create() {
            anyhow::bail!(
                "Tried to create a release while missing key fields: {}",
                self.missing().join(", ")
            )
        }
        let version = self.version.unwrap();
        let name = self.name.unwrap();
        let metadata = self.metadata;

        let hash_id = content_hash([name.as_bytes(), version.as_bytes()]);

        let request = CreateReleaseRequest {
            metadata,
            hash_id,
            version,
            project: name,
        };

        let client = &context().client;

        let response = client
            .send_post(client.project_url("error_tracking/releases")?, |req| {
                req.json(&request)
            })
            .context("Failed to create release")?;

        let response = response.json::<Release>()?;
        info!(
            "Release {}@{} created successfully! {}",
            request.project, request.version, response.id
        );
        Ok(response)
    }
}

/// Returns true if `err` (including wrapped causes) is the specific PostHog
/// API `validation_error` that signals a release with this `hash_id` already
/// exists. Used by the sourcemap upload flow to degrade gracefully when a
/// concurrent step has just created the release — `Release::lookup`'s
/// `by_hash` endpoint can briefly serve a stale 404 afterwards, so callers
/// that already have the correct release_id on their source pairs should
/// fall back to it instead of aborting.
///
/// The match is gated on all of:
/// - `ClientError::ApiError` with HTTP status `400`
/// - request URL path containing the releases endpoint
/// - JSON body parses as `ApiErrorResponse` with `code == "invalid_input"`
///   and `detail` containing "already in use"
///
/// The multiple gates are intentional: the raw response body is not a stable
/// wire contract, and a looser match could silently swallow unrelated 4xx
/// errors (e.g. a future endpoint that happens to emit the same English
/// phrase) and mask real bugs.
pub(crate) fn is_hash_already_in_use(err: &anyhow::Error) -> bool {
    err.chain().any(|cause| {
        let Some(ClientError::ApiError(status, url, body)) = cause.downcast_ref::<ClientError>()
        else {
            return false;
        };
        if *status != 400 {
            return false;
        }
        if !url.path().contains(RELEASES_PATH_SEGMENT) {
            return false;
        }
        let Ok(api_err) = serde_json::from_str::<ApiErrorResponse>(body) else {
            return false;
        };
        api_err.code == "invalid_input" && api_err.detail.contains("already in use")
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::Url;

    fn releases_url() -> Box<Url> {
        Box::new(
            Url::parse("https://us.posthog.com/api/projects/1/error_tracking/releases").unwrap(),
        )
    }

    fn api_err(status: u16, url: Box<Url>, body: &str) -> anyhow::Error {
        anyhow::Error::new(ClientError::ApiError(status, url, body.to_string()))
            .context("Failed to create release")
    }

    const HASH_IN_USE_BODY: &str = r#"{"type":"validation_error","code":"invalid_input","detail":"Hash id abc123 already in use","attr":null}"#;

    #[test]
    fn detects_hash_already_in_use_error() {
        assert!(is_hash_already_in_use(&api_err(
            400,
            releases_url(),
            HASH_IN_USE_BODY
        )));
    }

    #[test]
    fn ignores_non_400_status() {
        assert!(!is_hash_already_in_use(&api_err(
            500,
            releases_url(),
            HASH_IN_USE_BODY
        )));
    }

    #[test]
    fn ignores_wrong_endpoint() {
        let other_url = Box::new(
            Url::parse("https://us.posthog.com/api/projects/1/error_tracking/symbol_sets").unwrap(),
        );
        assert!(!is_hash_already_in_use(&api_err(
            400,
            other_url,
            HASH_IN_USE_BODY
        )));
    }

    #[test]
    fn ignores_non_validation_error_code() {
        let body = r#"{"type":"validation_error","code":"unique_constraint","detail":"Hash id abc123 already in use","attr":null}"#;
        assert!(!is_hash_already_in_use(&api_err(400, releases_url(), body)));
    }

    #[test]
    fn ignores_non_json_body() {
        assert!(!is_hash_already_in_use(&api_err(
            400,
            releases_url(),
            "Hash id abc already in use"
        )));
    }

    #[test]
    fn ignores_non_api_errors() {
        assert!(!is_hash_already_in_use(&anyhow::anyhow!(
            "something totally unrelated"
        )));
    }
}
