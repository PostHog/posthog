use clap::Subcommand;

use crate::error::CapturedError;
use crate::invocation_context::context;

// Include the build-time generated registry from openapi-to-rust
#[allow(dead_code)]
mod registry {
    include!(concat!(env!("OUT_DIR"), "/registry.rs"));
}

use registry::{HttpMethod, OperationDef, ParamLocation, OPERATIONS};

#[derive(Subcommand)]
pub enum ApiCommand {
    /// List all available API operations
    List {
        /// Filter operations by tag/resource name (e.g. "feature_flags", "dashboards")
        #[arg(short, long)]
        filter: Option<String>,
    },

    /// Call an API operation by its operation ID
    Call {
        /// Operation ID (e.g. "feature_flags_list", "dashboards_retrieve")
        /// Use `posthog-cli api list` to see all available operations.
        operation_id: String,

        /// JSON object with parameters and request body.
        /// Path/query params are extracted by name, remaining fields become the request body.
        /// Example: '{"project_id": "12345", "limit": "10"}'
        #[arg(default_value = "{}")]
        params_json: String,
    },
}

impl ApiCommand {
    pub fn run(self) -> Result<(), CapturedError> {
        match self {
            ApiCommand::List { filter } => list_operations(filter),
            ApiCommand::Call {
                operation_id,
                params_json,
            } => call_operation(&operation_id, &params_json),
        }
    }
}

fn list_operations(filter: Option<String>) -> Result<(), CapturedError> {
    if OPERATIONS.is_empty() {
        eprintln!("No API operations available.");
        eprintln!("Run `hogli build:openapi-schema` then rebuild the CLI.");
        return Ok(());
    }

    let filter_lower = filter.as_deref().map(|s| s.to_lowercase());

    let mut printed = 0;
    for op in OPERATIONS.iter() {
        if let Some(ref f) = filter_lower {
            let id_lower = op.id.to_lowercase();
            let path_lower = op.path.to_lowercase();
            if !id_lower.contains(f) && !path_lower.contains(f) {
                continue;
            }
        }

        let summary = op.summary.unwrap_or("");
        println!(
            "  {:<8} {:<55} {}",
            op.method.as_str(),
            op.id,
            summary
        );
        printed += 1;
    }

    if printed == 0 {
        eprintln!(
            "No operations matched filter {:?}. Try `posthog-cli api list` to see all.",
            filter.unwrap_or_default()
        );
    } else {
        eprintln!("\n{printed} operations");
    }
    Ok(())
}

fn call_operation(operation_id: &str, params_json: &str) -> Result<(), CapturedError> {
    let op = find_operation(operation_id)?;

    let params: serde_json::Value = serde_json::from_str(params_json)
        .map_err(|e| anyhow::anyhow!("Invalid JSON params: {e}"))?;
    let params_map = params.as_object().cloned().unwrap_or_default();

    // Build the URL by substituting path parameters
    let mut path = op.path.to_string();
    let mut query_params: Vec<(String, String)> = Vec::new();
    let mut consumed_keys: std::collections::HashSet<String> = std::collections::HashSet::new();

    for param in op.params.iter() {
        let value = params_map.get(param.name).and_then(|v| match v {
            serde_json::Value::String(s) => Some(s.clone()),
            other => Some(other.to_string()),
        });

        match param.location {
            ParamLocation::Path => {
                if let Some(val) = &value {
                    path = path.replace(&format!("{{{}}}", param.name), val);
                    consumed_keys.insert(param.name.to_string());
                } else if param.required {
                    return Err(anyhow::anyhow!(
                        "Missing required path parameter: '{}'\nUsage: posthog-cli api call {} '{{\"{}\":\"...\"}}'",
                        param.name, operation_id, param.name
                    )
                    .into());
                }
            }
            ParamLocation::Query => {
                if let Some(val) = &value {
                    query_params.push((param.name.to_string(), val.clone()));
                    consumed_keys.insert(param.name.to_string());
                }
            }
            ParamLocation::Header => {
                // Headers are handled separately if needed; skip for now
                if value.is_some() {
                    consumed_keys.insert(param.name.to_string());
                }
            }
        }
    }

    // Remaining (unconsumed) params become the request body for POST/PUT/PATCH
    let body: Option<serde_json::Value> = if op.body.is_some() {
        let body_map: serde_json::Map<String, serde_json::Value> = params_map
            .into_iter()
            .filter(|(k, _)| !consumed_keys.contains(k))
            .collect();
        if body_map.is_empty() {
            None
        } else {
            Some(serde_json::Value::Object(body_map))
        }
    } else {
        None
    };

    // Build the full URL
    let ctx = context();
    let host = &ctx.config.host;
    let mut url = reqwest::Url::parse(host)
        .map_err(|e| anyhow::anyhow!("Invalid host URL: {e}"))?
        .join(&path)
        .map_err(|e| anyhow::anyhow!("Failed to build URL: {e}"))?;

    for (key, value) in &query_params {
        url.query_pairs_mut().append_pair(key, value);
    }

    // Make the request
    let method = match op.method {
        HttpMethod::Get => reqwest::Method::GET,
        HttpMethod::Post => reqwest::Method::POST,
        HttpMethod::Put => reqwest::Method::PUT,
        HttpMethod::Patch => reqwest::Method::PATCH,
        HttpMethod::Delete => reqwest::Method::DELETE,
    };

    let response = ctx.client.send_request(method, url, |req| {
        if let Some(ref body_json) = body {
            req.json(body_json)
        } else {
            req
        }
    });

    match response {
        Ok(resp) => {
            let text = resp.text().map_err(|e| anyhow::anyhow!("Failed to read response: {e}"))?;
            // Try to pretty-print JSON, fall back to raw text
            if let Ok(json) = serde_json::from_str::<serde_json::Value>(&text) {
                println!(
                    "{}",
                    serde_json::to_string_pretty(&json)
                        .unwrap_or(text)
                );
            } else {
                println!("{text}");
            }
            Ok(())
        }
        Err(e) => Err(anyhow::anyhow!("API request failed: {e}").into()),
    }
}

fn find_operation(id: &str) -> Result<&'static OperationDef, CapturedError> {
    // Exact match first
    if let Some(op) = registry::find_operation(id) {
        return Ok(op);
    }

    // Fuzzy match: try matching the end of operation IDs
    let candidates: Vec<&OperationDef> = OPERATIONS
        .iter()
        .filter(|op| op.id.ends_with(id) || op.id.contains(id))
        .collect();

    match candidates.len() {
        0 => {
            // Suggest similar operations
            let suggestions: Vec<&str> = OPERATIONS
                .iter()
                .filter(|op| {
                    let id_lower = op.id.to_lowercase();
                    let search_lower = id.to_lowercase();
                    id_lower
                        .split('_')
                        .any(|part| part.starts_with(&search_lower))
                        || search_lower
                            .split('_')
                            .any(|part| id_lower.contains(part))
                })
                .map(|op| op.id)
                .take(5)
                .collect();

            let mut msg = format!("Unknown operation: '{id}'");
            if !suggestions.is_empty() {
                msg.push_str("\n\nDid you mean one of these?");
                for s in suggestions {
                    msg.push_str(&format!("\n  {s}"));
                }
            }
            msg.push_str("\n\nUse `posthog-cli api list` to see all available operations.");
            Err(anyhow::anyhow!("{msg}").into())
        }
        1 => Ok(candidates[0]),
        _ => {
            let mut msg = format!("Ambiguous operation '{id}'. Matches:");
            for c in &candidates {
                msg.push_str(&format!("\n  {} {} {}", c.method.as_str(), c.id, c.path));
            }
            Err(anyhow::anyhow!("{msg}").into())
        }
    }
}
