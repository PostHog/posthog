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
    project: Option<String>,
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
    pub project: String,
}

impl Release {
    pub fn lookup(project: &str, version: &str) -> Result<Option<Self>, ClientError> {
        let hash_id = content_hash([project, version]);
        let client = &context().client;

        let path = format!("error_tracking/releases/hash/{hash_id}");
        let response = client.send_get(&path, |req| req);

        if let Err(err) = response {
            if let ClientError::ApiError(404, _, _) = err {
                warn!("release {} of project {} not found", version, project);
                return Ok(None);
            }
            warn!("failed to get release from hash: {}", err);
            Err(err)
        } else {
            info!("found release {} of project {}", version, project);
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
            project: info.repo_name,
        }
    }

    pub fn with_git(&mut self, info: GitInfo) -> &mut Self {
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

    pub fn with_project(&mut self, project: &str) -> &mut Self {
        self.project = Some(project.to_string());
        self
    }

    pub fn with_version(&mut self, version: &str) -> &mut Self {
        self.version = Some(version.to_string());
        self
    }

    pub fn can_create(&self) -> bool {
        self.version.is_some() && self.project.is_some()
    }

    pub fn missing(&self) -> Vec<&str> {
        let mut missing = Vec::new();

        if self.version.is_none() {
            missing.push("version");
        }
        if self.project.is_none() {
            missing.push("project");
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
        let project = self.project.as_ref().unwrap();
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
        let project = self.project.unwrap();
        let metadata = self.metadata;

        let hash_id = content_hash([project.as_bytes(), version.as_bytes()]);

        let request = CreateReleaseRequest {
            metadata,
            hash_id,
            version,
            project,
        };

        let client = &context().client;

        let response = client
            .send_post("error_tracking/releases", |req| req.json(&request))
            .context("Failed to create release")?;

        let response = response.json::<Release>()?;
        info!(
            "Release {} of {} created successfully! {}",
            request.version, request.project, response.id
        );
        Ok(response)
    }
}
