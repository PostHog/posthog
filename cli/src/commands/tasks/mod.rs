mod list;
mod progress;
mod update_stage;
mod utils;

use anyhow::Result;
use chrono::{DateTime, Utc};
use clap::Subcommand;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use self::list::list_tasks;
use self::progress::show_progress;
use self::update_stage::update_stage;

#[derive(Debug, Serialize, Deserialize)]
pub struct Task {
    pub id: Uuid,
    pub title: String,
    pub description: Option<String>,
    pub origin_product: String,
    pub position: i32,
    pub workflow: Option<Uuid>,
    pub current_stage: Option<Uuid>,
    pub github_integration: Option<i64>,
    pub repository_config: Option<Value>,
    pub repository_list: Option<Vec<Value>>,
    pub primary_repository: Option<Value>,
    pub github_branch: Option<String>,
    pub github_pr_url: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct WorkflowStage {
    pub id: Uuid,
    pub workflow: Uuid,
    pub name: String,
    pub key: String,
    pub position: i32,
    pub color: String,
    pub agent: Option<Uuid>,
    pub agent_name: Option<String>,
    pub is_manual_only: bool,
    pub is_archived: bool,
    pub fallback_stage: Option<Uuid>,
    pub task_count: Option<i32>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct AgentDefinition {
    pub id: Uuid,
    pub name: String,
    pub agent_type: String,
    pub description: Option<String>,
    pub config: Value, // JSON object
    pub is_active: bool,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TaskWorkflow {
    pub id: Uuid,
    pub name: String,
    pub description: Option<String>,
    pub color: String,
    pub is_default: bool,
    pub is_active: bool,
    pub version: i32,
    pub stages: Vec<WorkflowStage>,
    pub task_count: Option<i32>,
    pub can_delete: Option<CanDeleteResponse>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct CanDeleteResponse {
    pub can_delete: bool,
    pub reason: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct TaskListResponse {
    pub results: Vec<Task>,
    pub count: usize,
    pub next: Option<String>,
    pub previous: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct RepositoryConfig {
    pub integration_id: Option<i64>,
    pub organization: String,
    pub repository: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct WorkflowConfiguration {
    pub workflow: TaskWorkflow,
    pub stages: Vec<WorkflowStage>,
}

#[derive(Subcommand)]
pub enum TaskCommand {
    /// List all tasks
    List {
        /// Maximum number of tasks to display
        #[arg(long)]
        limit: Option<usize>,

        /// Page offset for pagination
        #[arg(long)]
        offset: Option<usize>,
    },

    /// View task progress
    Progress {
        /// Task ID (will prompt for selection if not provided)
        task_id: Option<Uuid>,
    },

    /// Update task stage
    UpdateStage {
        /// Task ID (will prompt for selection if not provided)
        task_id: Option<Uuid>,
    },
}

impl TaskCommand {
    pub fn run(&self) -> Result<()> {
        match self {
            TaskCommand::List { limit, offset } => list_tasks(limit.as_ref(), offset.as_ref()),
            TaskCommand::Progress { task_id } => show_progress(task_id.as_ref()),
            TaskCommand::UpdateStage { task_id } => update_stage(task_id.as_ref()),
        }
    }
}
