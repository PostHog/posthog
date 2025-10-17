use anyhow::{Context, Result};
use reqwest::blocking::Client;
use std::collections::VecDeque;

use crate::{
    experimental::tasks::{
        utils::{fetch_stages, fetch_tasks, fetch_workflows},
        Task,
    },
    invocation_context::context,
    utils::{auth::Token, raise_for_err},
};

use super::{TaskListResponse, TaskWorkflow, WorkflowStage};

const BUFFER_SIZE: usize = 50;

pub struct TaskIterator {
    client: Client,
    token: Token,
    buffer: VecDeque<Task>,
    next_url: Option<String>,
}

impl TaskIterator {
    pub fn new(client: Client, host: String, token: Token, offset: Option<usize>) -> Result<Self> {
        let initial_url = format!("{}/api/environments/{}/tasks/", host, token.env_id);
        let mut params = vec![];
        params.push(("limit", BUFFER_SIZE.to_string()));
        if let Some(offset) = offset {
            params.push(("offset", offset.to_string()));
        }

        let response = client
            .get(&initial_url)
            .query(&params)
            .header("Authorization", format!("Bearer {}", token.token))
            .send()
            .context("Failed to send request")?;

        let response = raise_for_err(response)?;

        let task_response: TaskListResponse = response
            .json()
            .context("Failed to parse task list response")?;

        let mut buffer = VecDeque::new();
        buffer.extend(task_response.results);

        Ok(Self {
            client,
            token,
            buffer,
            next_url: task_response.next,
        })
    }

    fn fetch_next_batch(&mut self) -> Result<bool> {
        let url = if let Some(next_url) = &self.next_url {
            next_url.clone()
        } else {
            return Ok(false);
        };

        let response = self
            .client
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.token.token))
            .send()
            .context("Failed to send request")?;

        let response = raise_for_err(response)?;

        let task_response: TaskListResponse = response
            .json()
            .context("Failed to parse task list response")?;

        self.buffer.extend(task_response.results);
        self.next_url = task_response.next;

        Ok(!self.buffer.is_empty())
    }
}

impl Iterator for TaskIterator {
    type Item = Result<Task>;

    fn next(&mut self) -> Option<Self::Item> {
        if self.buffer.is_empty() {
            match self.fetch_next_batch() {
                Ok(has_data) => {
                    if !has_data {
                        return None;
                    }
                }
                Err(e) => return Some(Err(e)),
            }
        }

        self.buffer.pop_front().map(Ok)
    }
}

pub fn print_task(task: &Task, workflows: &[TaskWorkflow], stages: &[WorkflowStage]) {
    println!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    println!("ID: {}", task.id);
    println!("Title: {}", task.title);

    if let Some(desc) = &task.description {
        if !desc.is_empty() {
            println!("Description: {desc}");
        }
    }

    println!("Origin Product: {}", task.origin_product);
    println!("Position: {}", task.position);

    if let Some(workflow_id) = &task.workflow {
        if let Some(workflow) = workflows.iter().find(|w| &w.id == workflow_id) {
            println!(
                "Workflow: {}{}",
                workflow.name,
                if workflow.is_default {
                    " (default)"
                } else {
                    ""
                }
            );
        } else {
            println!("Workflow: {workflow_id} (unknown)");
        }
    } else {
        println!("Workflow: None");
    }

    if let Some(stage_id) = &task.current_stage {
        if let Some(stage) = stages.iter().find(|s| &s.id == stage_id) {
            println!("Stage: {} ({})", stage.name, stage.key);
        } else {
            println!("Stage: {stage_id} (unknown)");
        }
    } else {
        println!("Stage: None");
    }

    if let Some(primary_repo) = &task.primary_repository {
        if let Some(org) = primary_repo.get("organization").and_then(|v| v.as_str()) {
            if let Some(repo) = primary_repo.get("repository").and_then(|v| v.as_str()) {
                println!("Repository: {org}/{repo}");
            }
        }
    }

    if let Some(branch) = &task.github_branch {
        println!("GitHub Branch: {branch}");
    }

    if let Some(pr_url) = &task.github_pr_url {
        println!("GitHub PR: {pr_url}");
    }

    println!("Created: {}", task.created_at.format("%Y-%m-%d %H:%M UTC"));
    println!("Updated: {}", task.updated_at.format("%Y-%m-%d %H:%M UTC"));
}

pub fn list_tasks(limit: Option<&usize>, offset: Option<&usize>) -> Result<()> {
    let token = context().token.clone();
    let host = token.get_host();
    let client = context().client.clone();

    let workflows: Result<Vec<TaskWorkflow>> =
        fetch_workflows(client.clone(), host.clone(), token.clone())?.collect();
    let workflows = workflows?;

    let stages: Result<Vec<WorkflowStage>> =
        fetch_stages(client.clone(), host.clone(), token.clone())?.collect();
    let stages = stages?;

    let tasks = fetch_tasks(client, host, token, offset.cloned())?;

    let task_iter: Box<dyn Iterator<Item = Result<Task>>> = if let Some(limit) = limit {
        Box::new(tasks.take(*limit))
    } else {
        Box::new(tasks)
    };

    for task in task_iter {
        print_task(&task?, &workflows, &stages);
    }

    Ok(())
}
