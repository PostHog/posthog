use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::{
    experimental::tasks::utils::select_task, invocation_context::context, utils::raise_for_err,
};

#[derive(Debug, Serialize, Deserialize)]
struct TaskProgressResponse {
    has_progress: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    id: Option<Uuid>,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    current_step: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    completed_steps: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total_steps: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    progress_percentage: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    output_log: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error_message: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    created_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    updated_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    completed_at: Option<DateTime<Utc>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    workflow_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    workflow_run_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    message: Option<String>,
}

pub fn show_progress(task_id: Option<&Uuid>) -> Result<()> {
    // Get the task ID either from the argument or through interactive selection
    let task_id = match task_id {
        Some(id) => *id,
        None => select_task("Select a task to view progress:")?.id,
    };

    // Fetch and display progress
    let progress = fetch_progress(&task_id)?;
    print_progress(&task_id, &progress);

    Ok(())
}

fn fetch_progress(task_id: &Uuid) -> Result<TaskProgressResponse> {
    let client = context().client.clone();

    let path = format!("tasks/{task_id}/progress/");
    let response = client
        .get(&path)?
        .send()
        .context("Failed to send request")?;
    let response = raise_for_err(response)?;

    let progress: TaskProgressResponse = response
        .json()
        .context("Failed to parse progress response")?;

    Ok(progress)
}

fn print_progress(task_id: &Uuid, progress: &TaskProgressResponse) {
    println!("\nProgress for Task {task_id}:\n");

    if !progress.has_progress {
        println!(
            "{}",
            progress
                .message
                .as_deref()
                .unwrap_or("No execution progress found for this task")
        );
        return;
    }

    if let Some(status) = &progress.status {
        println!("Status: {status}");
    }

    if let Some(percentage) = progress.progress_percentage {
        let filled = (percentage / 2.0) as usize;
        let empty = 50 - filled;
        let bar = format!(
            "[{}{}] {:.1}%",
            "█".repeat(filled),
            "░".repeat(empty),
            percentage
        );
        println!("Progress: {bar}");
    }

    if let Some(current_step) = &progress.current_step {
        if !current_step.is_empty() {
            println!("Current Step: {current_step}");
        }
    }

    if let (Some(completed), Some(total)) = (progress.completed_steps, progress.total_steps) {
        println!("Steps: {completed} / {total}");
    }

    if let Some(workflow_id) = &progress.workflow_id {
        if !workflow_id.is_empty() {
            println!("\nWorkflow ID: {workflow_id}");
        }
    }

    if let Some(workflow_run_id) = &progress.workflow_run_id {
        if !workflow_run_id.is_empty() {
            println!("Workflow Run ID: {workflow_run_id}");
        }
    }

    if let Some(output_log) = &progress.output_log {
        if !output_log.is_empty() {
            println!("\nOutput:");
            println!("{}", "─".repeat(60));
            for line in output_log.lines() {
                println!("{line}");
            }
            println!("{}", "─".repeat(60));
        }
    }

    if let Some(error_message) = &progress.error_message {
        if !error_message.is_empty() {
            println!("\nError:");
            println!("{}", "─".repeat(60));
            for line in error_message.lines() {
                println!("{line}");
            }
            println!("{}", "─".repeat(60));
        }
    }

    println!("\nTimestamps:");
    if let Some(created_at) = progress.created_at {
        println!("  Started: {}", created_at.format("%Y-%m-%d %H:%M:%S UTC"));
    }
    if let Some(updated_at) = progress.updated_at {
        println!(
            "  Last Updated: {}",
            updated_at.format("%Y-%m-%d %H:%M:%S UTC")
        );
    }
    if let Some(completed_at) = progress.completed_at {
        println!(
            "  Completed: {}",
            completed_at.format("%Y-%m-%d %H:%M:%S UTC")
        );
    }
}
