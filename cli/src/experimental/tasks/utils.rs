use anyhow::{Context, Result};
use inquire::Select;
use std::collections::VecDeque;

use super::{Task, TaskWorkflow, WorkflowStage};
use crate::{
    api::client::PHClient, experimental::tasks::list::TaskIterator, invocation_context::context,
};

const PAGE_SIZE: usize = 10;
const BUFFER_SIZE: usize = 50;

#[allow(clippy::large_enum_variant)]
enum SelectionChoice {
    Task(Task),
    Next,
}

impl std::fmt::Display for SelectionChoice {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SelectionChoice::Task(task) => {
                write!(f, "{} - {}", task.title, task.origin_product)
            }
            SelectionChoice::Next => write!(f, "→ Load more tasks..."),
        }
    }
}

pub fn select_task(prompt: &str) -> Result<Task> {
    let client = context().client.clone();

    let mut task_iter = fetch_tasks(client, None)?;

    loop {
        let mut choices = Vec::new();

        // Fetch up to PAGE_SIZE tasks
        for _ in 0..PAGE_SIZE {
            match task_iter.next() {
                Some(Ok(task)) => choices.push(SelectionChoice::Task(task)),
                Some(Err(e)) => return Err(e),
                None => break,
            }
        }

        if choices.is_empty() {
            anyhow::bail!("No tasks found.");
        }

        // If we got exactly PAGE_SIZE items, assume there might be more
        if choices.len() == PAGE_SIZE {
            choices.push(SelectionChoice::Next);
        }

        let selection = Select::new(prompt, choices)
            .prompt()
            .context("Failed to get task selection")?;

        match selection {
            SelectionChoice::Task(task) => return Ok(task),
            SelectionChoice::Next => continue,
        }
    }
}

pub fn fetch_tasks(client: PHClient, offset: Option<usize>) -> Result<TaskIterator> {
    TaskIterator::new(client, offset)
}

#[derive(serde::Deserialize)]
struct WorkflowListResponse {
    results: Vec<TaskWorkflow>,
    next: Option<String>,
}

pub struct WorkflowIterator {
    client: PHClient,
    buffer: VecDeque<TaskWorkflow>,
    next_url: Option<String>,
}

impl WorkflowIterator {
    fn new(client: PHClient) -> Result<Self> {
        let response = client
            .get(&format!("task_workflows/?limit={BUFFER_SIZE}"))?
            .send()
            .context("Failed to send request")?;

        if !response.status().is_success() {
            // Return empty iterator on error, don't fail
            return Ok(Self {
                client: client.clone(),
                buffer: VecDeque::new(),
                next_url: None,
            });
        }

        let workflow_response: WorkflowListResponse = response
            .json()
            .context("Failed to parse workflow list response")?;

        let mut buffer = VecDeque::new();
        buffer.extend(workflow_response.results);

        Ok(Self {
            client,
            buffer,
            next_url: workflow_response.next,
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
            .get(&url)?
            .send()
            .context("Failed to send request")?;

        if !response.status().is_success() {
            return Ok(false);
        }

        let workflow_response: WorkflowListResponse = response
            .json()
            .context("Failed to parse workflow list response")?;

        self.buffer.extend(workflow_response.results);
        self.next_url = workflow_response.next;

        Ok(!self.buffer.is_empty())
    }
}

impl Iterator for WorkflowIterator {
    type Item = Result<TaskWorkflow>;

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

pub fn fetch_workflows(client: PHClient) -> Result<WorkflowIterator> {
    WorkflowIterator::new(client)
}

#[derive(serde::Deserialize)]
struct StageListResponse {
    results: Vec<WorkflowStage>,
    next: Option<String>,
}

pub struct StageIterator {
    client: PHClient,
    buffer: VecDeque<WorkflowStage>,
    next_url: Option<String>,
}

impl StageIterator {
    fn new(client: PHClient) -> Result<Self> {
        let response = client
            .get(&format!("workflow_stages/?limit={BUFFER_SIZE}"))?
            .send()
            .context("Failed to send request")?;

        if !response.status().is_success() {
            return Ok(Self {
                client,
                buffer: VecDeque::new(),
                next_url: None,
            });
        }

        let stage_response: StageListResponse = response
            .json()
            .context("Failed to parse stage list response")?;

        let mut buffer = VecDeque::new();
        buffer.extend(stage_response.results);

        Ok(Self {
            client,
            buffer,
            next_url: stage_response.next,
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
            .get(&url)?
            .send()
            .context("Failed to send request")?;

        if !response.status().is_success() {
            return Ok(false);
        }

        let stage_response: StageListResponse = response
            .json()
            .context("Failed to parse stage list response")?;

        self.buffer.extend(stage_response.results);
        self.next_url = stage_response.next;

        Ok(!self.buffer.is_empty())
    }
}

impl Iterator for StageIterator {
    type Item = Result<WorkflowStage>;

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

pub fn fetch_stages(client: PHClient) -> Result<StageIterator> {
    StageIterator::new(client)
}
