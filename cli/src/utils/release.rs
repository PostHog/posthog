use std::{collections::HashMap, path::PathBuf};

use anyhow::Result;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tracing::{info, warn};
use uuid::Uuid;

use crate::utils::client::get_client;

use super::{auth::Token, git::get_git_info};

#[derive(Debug, Clone, Serialize, Deserialize)]
struct CreateReleaseRequest {
    #[serde(skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,
    pub hash_id: Option<String>,
    pub version: String,
    pub project: String,
}

// The API returns more than this, but we only care about the ID
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CreateReleaseResponse {
    pub id: Uuid,
}

pub fn create_release(
    host: &str,
    token: &Token,
    dir: Option<PathBuf>,
    hash_id: Option<String>,
    project: Option<String>,
    version: Option<String>,
) -> Result<Option<CreateReleaseResponse>> {
    let git_info = get_git_info(dir)?;

    let Some(version) = version.or(git_info.as_ref().map(|g| g.commit_id.clone())) else {
        warn!(
            "Could not create release - no version provided, and one could not be derived via git"
        );
        return Ok(None);
    };

    let project = project.or_else(|| git_info.as_ref().and_then(|g| g.repo_name.clone()));
    let Some(project) = project else {
        warn!("Could not create release - no project name provided, and one could not be derived via git");
        return Ok(None);
    };

    let mut metadata = HashMap::new();
    if let Some(git_info) = git_info {
        metadata.insert("git".to_string(), serde_json::to_value(git_info)?);
    }

    let request = CreateReleaseRequest {
        metadata,
        hash_id,
        version,
        project,
    };

    let url = format!(
        "{}/api/environments/{}/error_tracking/releases",
        host, token.env_id
    );

    let client = get_client()?;

    let response = client
        .post(&url)
        .header("Authorization", format!("Bearer {}", token.token))
        .header("Content-Type", "application/json")
        .json(&request)
        .send()?;

    if response.status().is_success() {
        let response = response.json::<CreateReleaseResponse>()?;
        info!(
            "Release {} of {} created successfully! {}",
            request.version, request.project, response.id
        );
        Ok(Some(response))
    } else {
        let e = response.text()?;
        Err(anyhow::anyhow!("Failed to create release: {}", e))
    }
}
