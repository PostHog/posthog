use anyhow::{Context, Result};
use inquire::Select;
use reqwest::blocking::Client;
use serde::Serialize;
use uuid::Uuid;

use super::{Task, TaskWorkflow, WorkflowStage};
use crate::{
    experimental::tasks::utils::select_task, invocation_context::context, utils::raise_for_err,
};

struct StageChoice(WorkflowStage);

impl std::fmt::Display for StageChoice {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{} ({})", self.0.name, self.0.key)
    }
}

#[derive(Debug, Serialize)]
struct UpdateStageRequest {
    current_stage: Uuid,
}

pub fn update_stage(task_id: Option<&Uuid>) -> Result<()> {
    let token = context().token.clone();
    let host = token.get_host();
    let client = context().client.clone();

    let task = match task_id {
        Some(id) => fetch_task(&client, &host, &token, id)?,
        None => select_task("Select a task to update stage:")?,
    };

    println!("\nTask: {}", task.title);

    let workflow_id = match task.workflow {
        Some(id) => id,
        None => {
            anyhow::bail!("This task is not associated with any workflow. Cannot update stage.");
        }
    };

    let workflow = fetch_workflow(&client, &host, &token, &workflow_id)?;

    if workflow.stages.is_empty() {
        anyhow::bail!("The workflow '{}' has no stages defined.", workflow.name);
    }

    if let Some(current_stage_id) = &task.current_stage {
        if let Some(current_stage) = workflow.stages.iter().find(|s| &s.id == current_stage_id) {
            println!(
                "Current Stage: {} ({})",
                current_stage.name, current_stage.key
            );
        }
    } else {
        println!("Current Stage: None");
    }

    let available_stages: Vec<StageChoice> = workflow
        .stages
        .into_iter()
        .filter(|s| !s.is_archived)
        .map(StageChoice)
        .collect();

    if available_stages.is_empty() {
        anyhow::bail!("No active stages available in the workflow.");
    }

    println!("\nAvailable stages:");

    let selected_stage = Select::new("Select new stage:", available_stages)
        .prompt()
        .context("Failed to get stage selection")?;

    update_task_stage(&client, &host, &token, &task.id, &selected_stage.0.id)?;

    println!(
        "\n✓ Successfully updated task stage to: {} ({})",
        selected_stage.0.name, selected_stage.0.key
    );

    Ok(())
}

fn fetch_task(
    client: &Client,
    host: &str,
    token: &crate::utils::auth::Token,
    task_id: &Uuid,
) -> Result<Task> {
    let url = format!(
        "{}/api/environments/{}/tasks/{}/",
        host, token.env_id, task_id
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token.token))
        .send()
        .context("Failed to send request")?;

    let response = raise_for_err(response)?;

    let task: Task = response.json().context("Failed to parse task response")?;

    Ok(task)
}

fn fetch_workflow(
    client: &Client,
    host: &str,
    token: &crate::utils::auth::Token,
    workflow_id: &Uuid,
) -> Result<TaskWorkflow> {
    let url = format!(
        "{}/api/environments/{}/task_workflows/{}/",
        host, token.env_id, workflow_id
    );

    let response = client
        .get(&url)
        .header("Authorization", format!("Bearer {}", token.token))
        .send()
        .context("Failed to send request")?;

    let response = raise_for_err(response)?;

    let workflow: TaskWorkflow = response
        .json()
        .context("Failed to parse workflow response")?;

    Ok(workflow)
}

fn update_task_stage(
    client: &Client,
    host: &str,
    token: &crate::utils::auth::Token,
    task_id: &Uuid,
    stage_id: &Uuid,
) -> Result<()> {
    let url = format!(
        "{}/api/environments/{}/tasks/{}/update_stage/",
        host, token.env_id, task_id
    );

    let request_body = UpdateStageRequest {
        current_stage: *stage_id,
    };

    let response = client
        .patch(&url)
        .header("Authorization", format!("Bearer {}", token.token))
        .header("Content-Type", "application/json")
        .json(&request_body)
        .send()
        .context("Failed to send request")?;

    raise_for_err(response)?;

    Ok(())
}
