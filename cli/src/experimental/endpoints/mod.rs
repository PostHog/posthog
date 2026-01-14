mod diff;
mod get;
mod list;
mod open;
mod pull;
mod push;
mod run;

use anyhow::{Context, Result};
use clap::{Args, Subcommand};
use colored::Colorize;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use similar::{ChangeTag, TextDiff};
use std::collections::HashMap;

pub use diff::diff_endpoints;
pub use get::get_endpoint;
pub use list::list_endpoints;
pub use open::open_endpoint;
pub use pull::pull_endpoints;
pub use push::push_endpoints;
pub use run::run_endpoint;

use crate::invocation_context::context;

// ============================================================================
// Debug logging utilities
// ============================================================================

/// Log a debug message for API requests. Only prints if debug is true.
#[inline]
pub fn debug_request(debug: bool, method: &str, path: &str) {
    if debug {
        eprintln!("  {} {} {}", "DEBUG".cyan().bold(), method, path);
    }
}

/// Log a debug response body. Only prints if debug is true.
#[inline]
pub fn debug_response_body<T: serde::Serialize>(debug: bool, body: &T) {
    if debug {
        if let Ok(json) = serde_json::to_string_pretty(body) {
            eprintln!("  Response:\n{}", json.dimmed());
        }
    }
}

/// Log a debug error. Only prints if debug is true.
#[inline]
pub fn debug_error<E: std::fmt::Display>(debug: bool, error: &E) {
    if debug {
        eprintln!("  {} {}", "Error:".red(), error);
    }
}

/// YAML representation of an endpoint for local file storage.
/// This mirrors the API endpoint format but in a simpler YAML-friendly structure.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EndpointYaml {
    /// URL-safe name for the endpoint (required)
    pub name: String,

    /// Human-readable description of what this endpoint does
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,

    /// The HogQL query to execute (for simple HogQL queries)
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub query: Option<String>,

    /// Full query object for complex queries (TrendsQuery, FunnelsQuery, etc.)
    /// This takes precedence over the `query` field if both are specified.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub query_definition: Option<Value>,

    /// Query variables for parameterized queries
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub variables: Option<Vec<EndpointVariable>>,

    /// Materialization configuration
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub materialization: Option<MaterializationConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EndpointVariable {
    pub name: String,
    #[serde(rename = "type")]
    pub var_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default: Option<Value>,
}

/// Materialization configuration for an endpoint.
///
/// When enabled, PostHog will pre-compute and cache the query results
/// according to the specified schedule.
///
/// Valid schedule values:
/// - Minutes: "5min", "15min", "30min"
/// - Hours: "1hour", "2hour", "4hour", "6hour", "12hour", "24hour"
/// - Days: "7day", "30day"
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MaterializationConfig {
    #[serde(default)]
    pub enabled: bool,
    /// Sync frequency. Valid values: 5min, 15min, 30min, 1hour, 2hour, 4hour, 6hour, 12hour, 24hour, 7day, 30day
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub schedule: Option<String>,
}

/// API response for an endpoint from PostHog
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct EndpointResponse {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub description: String,
    pub query: Value,
    #[serde(default)]
    pub parameters: HashMap<String, Value>,
    pub is_active: bool,
    #[serde(default)]
    pub cache_age_seconds: Option<i64>,
    pub endpoint_path: String,
    #[serde(default)]
    pub url: Option<String>,
    #[serde(default)]
    pub ui_url: Option<String>,
    pub created_at: String,
    pub updated_at: String,
    pub is_materialized: bool,
    #[serde(default)]
    pub current_version: i32,
    #[serde(default)]
    pub versions_count: i32,
    #[serde(default)]
    pub materialization: Option<MaterializationStatus>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MaterializationStatus {
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub can_materialize: bool,
    #[serde(default)]
    pub last_materialized_at: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
    #[serde(default)]
    pub sync_frequency: Option<String>,
    #[serde(default)]
    pub reason: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct EndpointListResponse {
    pub results: Vec<EndpointResponse>,
}

#[derive(Subcommand)]
pub enum EndpointCommand {
    /// List all PostHog endpoints
    List(ListArgs),

    /// Get details of a specific PostHog endpoint
    Get(GetArgs),

    /// Open an endpoint in the browser
    Open(OpenArgs),

    /// Run an endpoint and see the results
    Run(RunArgs),

    /// Push local endpoint YAML files to PostHog
    Push(PushArgs),

    /// Pull PostHog endpoints to local endpoint YAML files
    Pull(PullArgs),

    /// Show differences between local YAML files and remote endpoints
    Diff(DiffArgs),
}

#[derive(Args, Clone)]
pub struct ListArgs {
    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct OpenArgs {
    /// Name of the endpoint to open
    pub name: String,

    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct GetArgs {
    /// Name of the endpoint to get
    pub name: String,

    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct RunArgs {
    /// Name of the endpoint to run
    #[arg(conflicts_with = "file")]
    pub name: Option<String>,

    /// Run query from a local YAML file (without creating endpoint)
    #[arg(long, short = 'f')]
    pub file: Option<String>,

    /// Pass a variable (can be used multiple times, format: name=value)
    #[arg(long = "var", short = 'v')]
    pub var: Vec<String>,

    /// Output raw JSON
    #[arg(long)]
    pub json: bool,

    /// Output format (table, json)
    #[arg(long)]
    pub format: Option<String>,

    /// Suppress status messages
    #[arg(long, short = 'q')]
    pub quiet: bool,

    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct PushArgs {
    /// Local PostHog YAML files or directories to push to PostHog
    #[arg(required = true)]
    pub paths: Vec<String>,

    /// Preview changes without applying
    #[arg(long)]
    pub dry_run: bool,

    /// Skip confirmation prompt
    #[arg(long, short = 'y')]
    pub yes: bool,

    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct PullArgs {
    /// Endpoint name(s) to pull
    #[arg()]
    pub names: Vec<String>,

    /// Pull all endpoints
    #[arg(long)]
    pub all: bool,

    /// Output path (directory for multiple endpoints, or .yaml/.yml file for single endpoint)
    #[arg(long, short = 'o', default_value = ".")]
    pub output: String,

    /// Preview changes without writing to YAML files
    #[arg(long)]
    pub dry_run: bool,

    /// Skip confirmation prompt
    #[arg(long, short = 'y')]
    pub yes: bool,

    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

#[derive(Args, Clone)]
pub struct DiffArgs {
    /// Local YAML files or directories to compare
    #[arg(required = true)]
    pub paths: Vec<String>,

    /// Show unchanged endpoints too
    #[arg(long, short = 'v')]
    pub verbose: bool,

    /// Show detailed API request/response information
    #[arg(long)]
    pub debug: bool,
}

impl EndpointCommand {
    pub fn run(&self) -> Result<()> {
        match self {
            EndpointCommand::List(args) => list_endpoints(args),
            EndpointCommand::Get(args) => get_endpoint(args),
            EndpointCommand::Open(args) => open_endpoint(args),
            EndpointCommand::Run(args) => run_endpoint(args),
            EndpointCommand::Push(args) => push_endpoints(args),
            EndpointCommand::Pull(args) => pull_endpoints(args),
            EndpointCommand::Diff(args) => diff_endpoints(args),
        }
    }
}

/// Resolved variable mapping: code_name -> (variableId, InsightVariable)
pub type ResolvedVariables = HashMap<String, (String, InsightVariable)>;

impl EndpointYaml {
    /// Convert this YAML representation to an API request body.
    /// If resolved_variables is provided, includes the variables in the query.
    pub fn to_api_request(&self, resolved_variables: Option<&ResolvedVariables>) -> Value {
        let mut request = serde_json::Map::new();

        request.insert("name".to_string(), Value::String(self.name.clone()));

        if let Some(desc) = &self.description {
            request.insert("description".to_string(), Value::String(desc.clone()));
        }

        // Build the query object
        let mut query = if let Some(query_def) = &self.query_definition {
            // Use the full query definition if provided
            query_def.clone()
        } else if let Some(hogql) = &self.query {
            // Build a HogQLQuery from the simple query string
            let mut q = serde_json::Map::new();
            q.insert("kind".to_string(), Value::String("HogQLQuery".to_string()));
            q.insert("query".to_string(), Value::String(hogql.clone()));
            Value::Object(q)
        } else {
            // No query specified - this should be caught during validation
            Value::Null
        };

        // Add resolved variables to the query object
        if let (Some(resolved), Some(local_vars)) = (resolved_variables, &self.variables) {
            if !local_vars.is_empty() {
                let mut vars_obj = serde_json::Map::new();
                for local_var in local_vars {
                    if let Some((var_id, insight_var)) = resolved.get(&local_var.name) {
                        let mut var_entry = serde_json::Map::new();
                        var_entry.insert("variableId".to_string(), Value::String(var_id.clone()));
                        var_entry.insert(
                            "code_name".to_string(),
                            Value::String(insight_var.code_name.clone()),
                        );
                        if let Some(default) = &local_var.default {
                            var_entry.insert("value".to_string(), default.clone());
                        }
                        vars_obj.insert(var_id.clone(), Value::Object(var_entry));
                    }
                }
                if !vars_obj.is_empty() {
                    if let Value::Object(ref mut q) = query {
                        q.insert("variables".to_string(), Value::Object(vars_obj));
                    }
                }
            }
        }

        request.insert("query".to_string(), query);

        // Handle materialization
        if let Some(mat) = &self.materialization {
            request.insert("is_materialized".to_string(), Value::Bool(mat.enabled));
            if let Some(schedule) = &mat.schedule {
                request.insert(
                    "sync_frequency".to_string(),
                    Value::String(schedule.clone()),
                );
            }
        }

        Value::Object(request)
    }

    /// Extract variable references from the query string.
    /// Looks for patterns like {variables.code_name}
    pub fn get_variable_references(&self) -> Vec<String> {
        let query_str = self.query.as_deref().unwrap_or("");
        extract_variable_references(query_str)
    }

    /// Create an EndpointYaml from an API response
    pub fn from_api_response(response: &EndpointResponse) -> Self {
        let (query, query_definition) = if let Some(kind) = response.query.get("kind") {
            if kind == "HogQLQuery" {
                // Simple HogQL query - extract just the query string
                let query_str = response
                    .query
                    .get("query")
                    .and_then(|q| q.as_str())
                    .map(|s| s.to_string());
                (query_str, None)
            } else {
                // Complex query - store the full definition
                (None, Some(response.query.clone()))
            }
        } else {
            (None, Some(response.query.clone()))
        };

        // Extract variables from the query object
        let variables = response
            .query
            .get("variables")
            .and_then(|v| v.as_object())
            .map(|vars_map| {
                vars_map
                    .values()
                    .filter_map(|var| {
                        let code_name = var.get("code_name")?.as_str()?.to_string();
                        let default = var.get("value").cloned();
                        // Infer type from the default value
                        let var_type = match &default {
                            Some(Value::Number(n)) => {
                                if n.is_i64() || n.is_u64() {
                                    "integer"
                                } else {
                                    "number"
                                }
                            }
                            Some(Value::Bool(_)) => "boolean",
                            Some(Value::String(_)) => "string",
                            Some(Value::Array(_)) => "array",
                            Some(Value::Object(_)) => "object",
                            Some(Value::Null) | None => "string",
                        };
                        Some(EndpointVariable {
                            name: code_name,
                            var_type: var_type.to_string(),
                            default,
                        })
                    })
                    .collect::<Vec<_>>()
            })
            .filter(|v: &Vec<EndpointVariable>| !v.is_empty());

        let materialization = if response.is_materialized {
            let schedule = response
                .materialization
                .as_ref()
                .and_then(|m| m.sync_frequency.as_ref())
                .cloned();
            Some(MaterializationConfig {
                enabled: true,
                schedule,
            })
        } else {
            None
        };

        EndpointYaml {
            name: response.name.clone(),
            description: if response.description.is_empty() {
                None
            } else {
                Some(response.description.clone())
            },
            query,
            query_definition,
            variables,
            materialization,
        }
    }

    /// Validate the endpoint YAML (basic structural checks only, backend validates the rest)
    pub fn validate(&self) -> Result<()> {
        if self.name.is_empty() {
            anyhow::bail!("Endpoint name is required");
        }

        if self.query.is_none() && self.query_definition.is_none() {
            anyhow::bail!(
                "Either 'query' or 'query_definition' is required for endpoint '{}'",
                self.name
            );
        }

        Ok(())
    }
}

// ============================================================================
// Shared utilities for push/pull change tracking
// ============================================================================

/// Represents a change between local and remote endpoint state
#[derive(Debug, Clone)]
pub enum Change {
    Description { from: String, to: String },
    Query { from: String, to: String },
    QueryDefinition { from: String, to: String },
    Materialization { from: bool, to: bool },
    Schedule { from: String, to: String },
    Variables { from: Vec<String>, to: Vec<String> },
}

/// Format a change for human-readable display
pub fn format_change_summary(change: &Change) -> String {
    match change {
        Change::Description { from, to } => {
            format!(
                "Description: {} → {}",
                if from.is_empty() {
                    "(empty)"
                } else {
                    from.as_str()
                },
                if to.is_empty() {
                    "(empty)"
                } else {
                    to.as_str()
                }
            )
        }
        Change::Query { .. } => "Query".to_string(),
        Change::QueryDefinition { .. } => "Query definition".to_string(),
        Change::Materialization { from, to } => {
            format!(
                "Materialization: {} → {}",
                if *from { "enabled" } else { "disabled" },
                if *to { "enabled" } else { "disabled" }
            )
        }
        Change::Schedule { from, to } => {
            format!(
                "Schedule: {} → {}",
                if from.is_empty() {
                    "(none)"
                } else {
                    from.as_str()
                },
                if to.is_empty() { "(none)" } else { to.as_str() }
            )
        }
        Change::Variables { from, to } => {
            let from_str = if from.is_empty() {
                "(none)".to_string()
            } else {
                from.join(", ")
            };
            let to_str = if to.is_empty() {
                "(none)".to_string()
            } else {
                to.join(", ")
            };
            format!("Variables: [{from_str}] → [{to_str}]")
        }
    }
}

/// Print a unified diff of two strings with colored output
pub fn print_diff(from: &str, to: &str, indent: &str) {
    let diff = TextDiff::from_lines(from, to);

    for change in diff.iter_all_changes() {
        let (sign, color_fn): (&str, fn(&str) -> colored::ColoredString) = match change.tag() {
            ChangeTag::Delete => ("-", |s: &str| s.red()),
            ChangeTag::Insert => ("+", |s: &str| s.green()),
            ChangeTag::Equal => (" ", |s: &str| s.dimmed()),
        };
        let line = change.to_string_lossy();
        let line_trimmed = line.trim_end_matches('\n');
        println!("{indent}{} {}", color_fn(sign), color_fn(line_trimmed));
    }
}

// ============================================================================
// Shared comparison helpers
// ============================================================================

/// Extract variable code_names from a remote endpoint response
pub fn get_remote_variable_names(remote: &EndpointResponse) -> Vec<String> {
    remote
        .query
        .get("variables")
        .and_then(|v| v.as_object())
        .map(|vars_map| {
            vars_map
                .values()
                .filter_map(|var| var.get("code_name")?.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default()
}

/// Get the schedule from local YAML (empty string if none)
pub fn get_local_schedule(local: &EndpointYaml) -> String {
    local
        .materialization
        .as_ref()
        .and_then(|m| m.schedule.clone())
        .unwrap_or_default()
}

/// Get the schedule from remote endpoint (empty string if none)
pub fn get_remote_schedule(remote: &EndpointResponse) -> String {
    remote
        .materialization
        .as_ref()
        .and_then(|m| m.sync_frequency.clone())
        .unwrap_or_default()
}

/// Compute changes between local and remote endpoints (for push/diff direction).
/// Returns changes where `from` is the remote state and `to` is the local state.
pub fn compute_changes_for_push(local: &EndpointYaml, remote: &EndpointResponse) -> Vec<Change> {
    let mut changes = Vec::new();

    // Description
    let local_desc = local.description.as_deref().unwrap_or("");
    if local_desc != remote.description {
        changes.push(Change::Description {
            from: remote.description.clone(),
            to: local_desc.to_string(),
        });
    }

    // Query (for HogQL queries)
    let local_query = local.query.as_deref().unwrap_or("");
    let remote_query = remote
        .query
        .get("query")
        .and_then(|q| q.as_str())
        .unwrap_or("");

    if !local_query.is_empty() && local_query != remote_query {
        changes.push(Change::Query {
            from: remote_query.to_string(),
            to: local_query.to_string(),
        });
    } else if let Some(local_def) = &local.query_definition {
        let local_json = serde_json::to_string_pretty(local_def).unwrap_or_default();
        let remote_json = serde_json::to_string_pretty(&remote.query).unwrap_or_default();
        if local_json != remote_json {
            changes.push(Change::QueryDefinition {
                from: remote_json,
                to: local_json,
            });
        }
    }

    // Materialization enabled/disabled
    let local_mat = local
        .materialization
        .as_ref()
        .map(|m| m.enabled)
        .unwrap_or(false);
    if local_mat != remote.is_materialized {
        changes.push(Change::Materialization {
            from: remote.is_materialized,
            to: local_mat,
        });
    }

    // Schedule
    let local_schedule = get_local_schedule(local);
    let remote_schedule = get_remote_schedule(remote);
    if local_schedule != remote_schedule {
        changes.push(Change::Schedule {
            from: remote_schedule,
            to: local_schedule,
        });
    }

    // Variables
    let local_vars: Vec<String> = local
        .variables
        .as_ref()
        .map(|vars| vars.iter().map(|v| v.name.clone()).collect())
        .unwrap_or_default();
    let remote_vars = get_remote_variable_names(remote);

    let mut local_sorted = local_vars.clone();
    let mut remote_sorted = remote_vars.clone();
    local_sorted.sort();
    remote_sorted.sort();

    if local_sorted != remote_sorted {
        changes.push(Change::Variables {
            from: remote_vars,
            to: local_vars,
        });
    }

    changes
}

// ============================================================================
// InsightVariable API types
// ============================================================================

/// PostHog InsightVariable from the API
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct InsightVariable {
    pub id: String,
    pub name: String,
    pub code_name: String,
    #[serde(rename = "type")]
    pub var_type: String,
    #[serde(default)]
    pub default_value: Option<Value>,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct InsightVariableListResponse {
    pub results: Vec<InsightVariable>,
}

/// Request body for creating an InsightVariable
#[derive(Debug, Serialize)]
pub struct CreateInsightVariableRequest {
    pub name: String,
    pub code_name: String,
    #[serde(rename = "type")]
    pub var_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_value: Option<Value>,
}

// ============================================================================
// Shared API helpers
// ============================================================================

/// Fetch all insight variables for the current environment
pub fn fetch_insight_variables(debug: bool) -> Result<Vec<InsightVariable>> {
    let client = &context().client;
    debug_request(debug, "GET", "insight_variables/");

    let result = client.send_get(client.env_url("insight_variables/")?, |req| req);

    match result {
        Ok(response) => {
            let list: InsightVariableListResponse = response
                .json()
                .context("Failed to parse insight variables response")?;
            if debug {
                eprintln!(
                    "  Response: {} variable{}",
                    list.results.len(),
                    if list.results.len() == 1 { "" } else { "s" }
                );
            }
            Ok(list.results)
        }
        Err(e) => {
            debug_error(debug, &e);
            Err(e).context("Failed to fetch insight variables")
        }
    }
}

/// Create a new insight variable
/// If debug is true, prints the request body and any error response
pub fn create_insight_variable(
    request: &CreateInsightVariableRequest,
    debug: bool,
) -> Result<InsightVariable> {
    let client = &context().client;

    if debug {
        eprintln!("  {} POST insight_variables/", "DEBUG".cyan().bold());
        if let Ok(json) = serde_json::to_string_pretty(request) {
            eprintln!("  Request body:\n{}", json.dimmed());
        }
    }

    let result = client.send_post(client.env_url("insight_variables/")?, |req| {
        req.json(request)
    });

    match result {
        Ok(response) => response.json().context("Failed to parse variable response"),
        Err(e) => {
            if debug {
                eprintln!("  {} {}", "Error:".red(), e);
            }
            Err(e).with_context(|| format!("Failed to create variable '{}'", request.code_name))
        }
    }
}

/// Fetch a single endpoint by name from PostHog
pub fn fetch_endpoint(name: &str, debug: bool) -> Result<EndpointResponse> {
    let client = &context().client;
    let path = format!("endpoints/{name}/");
    debug_request(debug, "GET", &path);

    let url = client.env_url(&path)?;
    let result = client.send_get(url, |req| req);

    match result {
        Ok(response) => {
            let endpoint: EndpointResponse = response
                .json()
                .context("Failed to parse endpoint response")?;
            debug_response_body(debug, &endpoint);
            Ok(endpoint)
        }
        Err(e) => {
            debug_error(debug, &e);
            Err(e).with_context(|| format!("Failed to fetch endpoint '{name}'"))
        }
    }
}

/// Fetch all endpoints from PostHog
pub fn fetch_all_endpoints(debug: bool) -> Result<EndpointListResponse> {
    let client = &context().client;
    debug_request(debug, "GET", "endpoints/");

    let result = client.send_get(client.env_url("endpoints/")?, |req| req);

    match result {
        Ok(response) => {
            let list: EndpointListResponse = response
                .json()
                .context("Failed to parse endpoints response")?;
            if debug {
                eprintln!(
                    "  Response: {} endpoint{}",
                    list.results.len(),
                    if list.results.len() == 1 { "" } else { "s" }
                );
            }
            Ok(list)
        }
        Err(e) => {
            debug_error(debug, &e);
            Err(e).context("Failed to fetch endpoints")
        }
    }
}

// ============================================================================
// Variable reference extraction
// ============================================================================

/// Extract variable references from a HogQL query string.
/// Looks for patterns like {variables.code_name}
pub fn extract_variable_references(query: &str) -> Vec<String> {
    let re = regex::Regex::new(r"\{variables\.([a-zA-Z_][a-zA-Z0-9_]*)\}")
        .expect("valid regex pattern for variable references");
    re.captures_iter(query)
        .filter_map(|cap| cap.get(1).map(|m| m.as_str().to_string()))
        .collect()
}

// ============================================================================
// Schedule/frequency conversion helpers
// ============================================================================

/// Valid sync frequency values for materialization schedules.
///
/// These values map directly to what the PostHog API accepts:
/// - Minutes: "5min", "15min", "30min"
/// - Hours: "1hour", "2hour", "4hour", "6hour", "12hour", "24hour"
/// - Days: "7day", "30day"
pub const VALID_SYNC_FREQUENCIES: &[&str] = &[
    "5min", "15min", "30min", "1hour", "2hour", "4hour", "6hour", "12hour", "24hour", "7day",
    "30day",
];

#[cfg(test)]
mod tests {
    use super::*;

    // =========================================================================
    // YAML parsing tests
    // =========================================================================

    #[test]
    fn test_parse_simple_endpoint_yaml() {
        let yaml = r#"
name: my-endpoint
description: A test endpoint
query: SELECT count() FROM events
"#;
        let endpoint: EndpointYaml = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(endpoint.name, "my-endpoint");
        assert_eq!(endpoint.description, Some("A test endpoint".to_string()));
        assert_eq!(
            endpoint.query,
            Some("SELECT count() FROM events".to_string())
        );
        assert!(endpoint.query_definition.is_none());
        assert!(endpoint.variables.is_none());
        assert!(endpoint.materialization.is_none());
    }

    #[test]
    fn test_parse_endpoint_with_variables() {
        let yaml = r#"
name: events-by-type
query: SELECT count() FROM events WHERE event = {variables.event_type}
variables:
  - name: event_type
    type: string
    default: "$pageview"
"#;
        let endpoint: EndpointYaml = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(endpoint.name, "events-by-type");
        let vars = endpoint.variables.unwrap();
        assert_eq!(vars.len(), 1);
        assert_eq!(vars[0].name, "event_type");
        assert_eq!(vars[0].var_type, "string");
    }

    #[test]
    fn test_parse_endpoint_with_materialization() {
        let yaml = r#"
name: materialized-endpoint
query: SELECT count() FROM events
materialization:
  enabled: true
  schedule: "1hour"
"#;
        let endpoint: EndpointYaml = serde_yaml::from_str(yaml).unwrap();
        let mat = endpoint.materialization.unwrap();
        assert!(mat.enabled);
        assert_eq!(mat.schedule, Some("1hour".to_string()));
    }

    // =========================================================================
    // Variable extraction tests
    // =========================================================================

    #[test]
    fn test_extract_single_variable() {
        let query = "SELECT * FROM events WHERE event = {variables.event_name}";
        let vars = extract_variable_references(query);
        assert_eq!(vars, vec!["event_name"]);
    }

    #[test]
    fn test_extract_multiple_variables() {
        let query = "SELECT * FROM events WHERE event = {variables.event_name} AND timestamp > {variables.start_date}";
        let vars = extract_variable_references(query);
        assert_eq!(vars.len(), 2);
        assert!(vars.contains(&"event_name".to_string()));
        assert!(vars.contains(&"start_date".to_string()));
    }

    #[test]
    fn test_extract_no_variables() {
        let query = "SELECT count() FROM events";
        let vars = extract_variable_references(query);
        assert!(vars.is_empty());
    }

    #[test]
    fn test_extract_variable_with_underscores() {
        let query = "SELECT * FROM events WHERE prop = {variables.my_long_var_name}";
        let vars = extract_variable_references(query);
        assert_eq!(vars, vec!["my_long_var_name"]);
    }

    #[test]
    fn test_get_variable_references_from_endpoint() {
        let endpoint = EndpointYaml {
            name: "test".to_string(),
            description: None,
            query: Some("SELECT * FROM events WHERE type = {variables.event_type}".to_string()),
            query_definition: None,
            variables: Some(vec![
                EndpointVariable {
                    name: "event_type".to_string(),
                    var_type: "string".to_string(),
                    default: None,
                },
                EndpointVariable {
                    name: "unused_var".to_string(),
                    var_type: "string".to_string(),
                    default: None,
                },
            ]),
            materialization: None,
        };

        let refs = endpoint.get_variable_references();
        assert_eq!(refs, vec!["event_type"]);

        // This shows unused_var is NOT in query - push command will reject this
        let defined: Vec<_> = endpoint
            .variables
            .unwrap()
            .iter()
            .map(|v| v.name.clone())
            .collect();
        let unused: Vec<_> = defined.iter().filter(|v| !refs.contains(v)).collect();
        assert_eq!(unused, vec![&"unused_var".to_string()]);
    }

    // =========================================================================
    // Schedule validation tests
    // =========================================================================

    #[test]
    fn test_valid_sync_frequencies() {
        // Ensure all expected frequencies are in the list
        assert!(VALID_SYNC_FREQUENCIES.contains(&"5min"));
        assert!(VALID_SYNC_FREQUENCIES.contains(&"1hour"));
        assert!(VALID_SYNC_FREQUENCIES.contains(&"24hour"));
        assert!(VALID_SYNC_FREQUENCIES.contains(&"7day"));
    }

    #[test]
    fn test_invalid_sync_frequencies() {
        assert!(!VALID_SYNC_FREQUENCIES.contains(&"invalid"));
        assert!(!VALID_SYNC_FREQUENCIES.contains(&"*/5 * * * *")); // cron not supported
        assert!(!VALID_SYNC_FREQUENCIES.contains(&"3hour")); // not a valid option
    }

    // =========================================================================
    // API request building tests
    // =========================================================================

    #[test]
    fn test_to_api_request_simple() {
        let endpoint = EndpointYaml {
            name: "test".to_string(),
            description: Some("Test endpoint".to_string()),
            query: Some("SELECT 1".to_string()),
            query_definition: None,
            variables: None,
            materialization: None,
        };
        let request = endpoint.to_api_request(None);
        assert_eq!(request["name"], "test");
        assert_eq!(request["description"], "Test endpoint");
        assert_eq!(request["query"]["kind"], "HogQLQuery");
        assert_eq!(request["query"]["query"], "SELECT 1");
    }

    #[test]
    fn test_to_api_request_with_materialization() {
        let endpoint = EndpointYaml {
            name: "mat-test".to_string(),
            description: None,
            query: Some("SELECT 1".to_string()),
            query_definition: None,
            variables: None,
            materialization: Some(MaterializationConfig {
                enabled: true,
                schedule: Some("1hour".to_string()),
            }),
        };
        let request = endpoint.to_api_request(None);
        assert_eq!(request["is_materialized"], true);
        assert_eq!(request["sync_frequency"], "1hour");
    }

    // =========================================================================
    // Validation tests
    // =========================================================================

    #[test]
    fn test_validate_requires_name() {
        let endpoint = EndpointYaml {
            name: "".to_string(),
            description: None,
            query: Some("SELECT 1".to_string()),
            query_definition: None,
            variables: None,
            materialization: None,
        };
        assert!(endpoint.validate().is_err());
    }

    #[test]
    fn test_validate_requires_query() {
        let endpoint = EndpointYaml {
            name: "test".to_string(),
            description: None,
            query: None,
            query_definition: None,
            variables: None,
            materialization: None,
        };
        assert!(endpoint.validate().is_err());
    }

    #[test]
    fn test_validate_accepts_query_definition() {
        let endpoint = EndpointYaml {
            name: "test".to_string(),
            description: None,
            query: None,
            query_definition: Some(serde_json::json!({"kind": "TrendsQuery"})),
            variables: None,
            materialization: None,
        };
        assert!(endpoint.validate().is_ok());
    }

    // =========================================================================
    // Change detection tests
    // =========================================================================

    #[test]
    fn test_format_change_summary_description() {
        let change = Change::Description {
            from: "Old".to_string(),
            to: "New".to_string(),
        };
        let summary = format_change_summary(&change);
        assert!(summary.contains("Old"));
        assert!(summary.contains("New"));
    }

    #[test]
    fn test_format_change_summary_materialization() {
        let change = Change::Materialization {
            from: false,
            to: true,
        };
        let summary = format_change_summary(&change);
        assert!(summary.contains("disabled"));
        assert!(summary.contains("enabled"));
    }
}
