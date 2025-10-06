use anyhow::{Context, Result};
use inquire::Select;
use reqwest::blocking::Client;
use std::collections::VecDeque;

use super::{Task, TaskWorkflow, WorkflowStage};
use crate::commands::tasks::list::TaskIterator;
use crate::utils::auth::Token;

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
    let token = crate::utils::auth::load_token().context("Failed to load authentication token")?;
    let host = token.get_host(None);
    let client = crate::utils::client::get_client()?;

    let mut task_iter = fetch_tasks(client, host, token, None)?;

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

pub fn fetch_tasks(
    client: Client,
    host: String,
    token: Token,
    offset: Option<usize>,
) -> Result<TaskIterator> {
    TaskIterator::new(client, host, token, offset)
}

#[derive(serde::Deserialize)]
struct WorkflowListResponse {
    results: Vec<TaskWorkflow>,
    next: Option<String>,
}

pub struct WorkflowIterator {
    client: Client,
    token: Token,
    buffer: VecDeque<TaskWorkflow>,
    next_url: Option<String>,
}

impl WorkflowIterator {
    fn new(client: Client, host: String, token: Token) -> Result<Self> {
        let initial_url = format!(
            "{}/api/environments/{}/task_workflows/?limit={}",
            host, token.env_id, BUFFER_SIZE
        );

        let response = client
            .get(&initial_url)
            .header("Authorization", format!("Bearer {}", token.token))
            .send()
            .context("Failed to send request")?;

        if !response.status().is_success() {
            // Return empty iterator on error, don't fail
            return Ok(Self {
                client,
                token,
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
            token,
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
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.token.token))
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

pub fn fetch_workflows(client: Client, host: String, token: Token) -> Result<WorkflowIterator> {
    WorkflowIterator::new(client, host, token)
}

#[derive(serde::Deserialize)]
struct StageListResponse {
    results: Vec<WorkflowStage>,
    next: Option<String>,
}

pub struct StageIterator {
    client: Client,
    token: Token,
    buffer: VecDeque<WorkflowStage>,
    next_url: Option<String>,
}

impl StageIterator {
    fn new(client: Client, host: String, token: Token) -> Result<Self> {
        let initial_url = format!(
            "{}/api/environments/{}/workflow_stages/?limit={}",
            host, token.env_id, BUFFER_SIZE
        );

        let response = client
            .get(&initial_url)
            .header("Authorization", format!("Bearer {}", token.token))
            .send()
            .context("Failed to send request")?;

        if !response.status().is_success() {
            return Ok(Self {
                client,
                token,
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
            token,
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
            .get(&url)
            .header("Authorization", format!("Bearer {}", self.token.token))
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

pub fn fetch_stages(client: Client, host: String, token: Token) -> Result<StageIterator> {
    StageIterator::new(client, host, token)
}
