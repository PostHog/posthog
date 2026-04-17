use std::collections::HashMap;

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{info, warn};
use uuid::Uuid;

use crate::{
    api::client::ClientError,
    invocation_context::context,
    utils::{files::content_hash, git::GitInfo},
};

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
        // Clone so we can re-lookup if a concurrent caller wins the create race
        // (e.g. the inject and upload phases of `sourcemap process` both reach
        // `fetch_or_create` for the same release).
        let name = self.name.clone().expect("can_create() ensured name is set");
        let version = self
            .version
            .clone()
            .expect("can_create() ensured version is set");

        if let Some(release) = Release::lookup(&name, &version)? {
            return Ok(release);
        }

        match self.create_release() {
            Ok(release) => Ok(release),
            Err(err) if is_hash_already_in_use(&err) => {
                warn!(
                    "Release {}@{} reported as already in use on create; re-fetching",
                    name, version
                );
                Release::lookup(&name, &version)?.ok_or(err)
            }
            Err(err) => Err(err),
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

/// Returns true if `err` (including wrapped causes) is the PostHog API
/// `validation_error` that signals a release with this `hash_id` already
/// exists. Used to make `fetch_or_create` tolerant of GET/POST races where
/// `Release::lookup` returns 404 for a release that a concurrent caller
/// (or a prior phase of the same `sourcemap process` run) just created.
fn is_hash_already_in_use(err: &anyhow::Error) -> bool {
    err.chain().any(|cause| {
        matches!(
            cause.downcast_ref::<ClientError>(),
            Some(ClientError::ApiError(_, _, body)) if body.contains("already in use")
        )
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

    #[test]
    fn detects_hash_already_in_use_error() {
        let body = r#"{"type":"validation_error","code":"invalid_input","detail":"Hash id abc123 already in use","attr":null}"#;
        let client_err = ClientError::ApiError(400, releases_url(), body.to_string());
        let wrapped = anyhow::Error::new(client_err).context("Failed to create release");
        assert!(is_hash_already_in_use(&wrapped));
    }

    #[test]
    fn ignores_unrelated_api_errors() {
        let client_err =
            ClientError::ApiError(500, releases_url(), "internal server error".to_string());
        let wrapped = anyhow::Error::new(client_err).context("Failed to create release");
        assert!(!is_hash_already_in_use(&wrapped));
    }

    #[test]
    fn ignores_non_api_errors() {
        let err = anyhow::anyhow!("something totally unrelated");
        assert!(!is_hash_already_in_use(&err));
    }
}
