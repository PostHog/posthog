use std::collections::HashMap;
use std::fs;

use anyhow::{Context, Result};
use colored::Colorize;
use serde_json::Value;

use crate::invocation_context::context;

use super::{
    debug_error, debug_request, debug_response_body, fetch_endpoint, EndpointYaml, RunArgs,
};

pub fn run_endpoint(args: &RunArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_run");

    let client = &context().client;

    // Build the query to execute
    let (query, name) = if let Some(file_path) = &args.file {
        // Run from local file without creating endpoint
        let content = fs::read_to_string(file_path)
            .with_context(|| format!("Failed to read file: {file_path}"))?;
        let endpoint: EndpointYaml = serde_yaml::from_str(&content)
            .with_context(|| format!("Failed to parse YAML: {file_path}"))?;
        endpoint.validate()?;

        let query = if let Some(query_def) = endpoint.query_definition {
            query_def
        } else if let Some(hogql) = endpoint.query {
            serde_json::json!({
                "kind": "HogQLQuery",
                "query": hogql
            })
        } else {
            anyhow::bail!("No query found in YAML file");
        };

        (query, endpoint.name)
    } else if let Some(endpoint_name) = &args.name {
        // Run existing endpoint - fetch its query first
        let endpoint = fetch_endpoint(endpoint_name, args.debug)?;

        if !endpoint.is_active {
            anyhow::bail!("Endpoint '{endpoint_name}' is not active");
        }

        (endpoint.query, endpoint_name.clone())
    } else {
        anyhow::bail!("Either --file or endpoint name is required");
    };

    // Parse variables from command line
    let variables: HashMap<String, String> = args
        .var
        .iter()
        .filter_map(|v| {
            let parts: Vec<&str> = v.splitn(2, '=').collect();
            if parts.len() == 2 {
                Some((parts[0].to_string(), parts[1].to_string()))
            } else {
                eprintln!(
                    "{} Invalid variable format: {v} (expected name=value)",
                    "⚠".yellow(),
                );
                None
            }
        })
        .collect();

    // Build the run request
    let mut request_body = serde_json::json!({});

    if !variables.is_empty() {
        request_body["variables"] = serde_json::to_value(&variables)?;
    }

    if args.file.is_some() {
        // For file-based runs, we execute the query directly via the query endpoint
        if !args.quiet {
            println!("{} Running query from file...", "→".cyan());
            println!();
        }

        let mut query_request = serde_json::json!({
            "query": query,
            "name": "endpoints_cli"
        });

        if !variables.is_empty() {
            query_request["variables"] = serde_json::to_value(&variables)?;
        }

        debug_request(args.debug, "POST", "query/");
        if args.debug {
            if let Ok(json) = serde_json::to_string_pretty(&query_request) {
                eprintln!("  Request body:\n{}", json.dimmed());
            }
        }

        let api_result =
            client.send_post(client.env_url("query/")?, |req| req.json(&query_request));

        match api_result {
            Ok(response) => {
                let result: Value = response.json().context("Failed to parse query response")?;
                debug_response_body(args.debug, &result);
                print_results(&result, args)?;
            }
            Err(e) => {
                debug_error(args.debug, &e);
                return Err(e).context("Failed to execute query");
            }
        }
    } else {
        // For named endpoints, use the run endpoint
        if !args.quiet {
            println!("{} Running endpoint '{name}'...", "→".cyan());
            println!();
        }

        let path = format!("endpoints/{name}/run/");
        debug_request(args.debug, "POST", &path);
        if args.debug && !variables.is_empty() {
            if let Ok(json) = serde_json::to_string_pretty(&request_body) {
                eprintln!("  Request body:\n{}", json.dimmed());
            }
        }

        let url = client.env_url(&path)?;
        let api_result = client.send_post(url, |req| req.json(&request_body));

        match api_result {
            Ok(response) => {
                let result: Value = response.json().context("Failed to parse response")?;
                debug_response_body(args.debug, &result);
                print_results(&result, args)?;
            }
            Err(e) => {
                debug_error(args.debug, &e);
                return Err(e).context("Failed to run endpoint");
            }
        }
    }

    Ok(())
}

fn print_results(result: &Value, args: &RunArgs) -> Result<()> {
    if args.json {
        // Raw JSON output
        println!("{}", serde_json::to_string_pretty(result)?);
        return Ok(());
    }

    // Extract results array
    let results = result.get("results").and_then(|r| r.as_array());
    let columns = result.get("columns").and_then(|c| c.as_array());

    match (&results, &columns, &args.format) {
        (Some(rows), Some(cols), Some(format)) if format == "table" => {
            print_table(cols, rows)?;
        }
        (Some(rows), Some(cols), None) => {
            // Default: print table if small enough, otherwise summary
            if rows.len() <= 50 && cols.len() <= 10 {
                print_table(cols, rows)?;
            } else {
                print_summary(rows, cols)?;
            }
        }
        (Some(rows), None, _) => {
            // No columns, just print results
            println!("{}", serde_json::to_string_pretty(&rows)?);
        }
        _ => {
            // Fallback to full JSON
            println!("{}", serde_json::to_string_pretty(result)?);
        }
    }

    Ok(())
}

fn print_table(columns: &[Value], rows: &[Value]) -> Result<()> {
    if rows.is_empty() {
        println!("{}", "(no results)".dimmed());
        return Ok(());
    }

    // Get column names
    let col_names: Vec<String> = columns
        .iter()
        .map(|c| c.as_str().unwrap_or("?").to_string())
        .collect();

    // Calculate column widths
    let mut widths: Vec<usize> = col_names.iter().map(|c| c.len()).collect();

    for row in rows {
        if let Some(row_arr) = row.as_array() {
            for (i, cell) in row_arr.iter().enumerate() {
                if i < widths.len() {
                    let cell_str = format_cell(cell);
                    widths[i] = widths[i].max(cell_str.len()).min(40); // Cap at 40 chars
                }
            }
        }
    }

    // Print header
    let header: String = col_names
        .iter()
        .enumerate()
        .map(|(i, name)| format!("{name:width$}", width = widths[i]))
        .collect::<Vec<_>>()
        .join("  ");
    println!("{}", header.bold());

    // Print separator
    let separator: String = widths
        .iter()
        .map(|w| "─".repeat(*w))
        .collect::<Vec<_>>()
        .join("──");
    println!("{}", separator.dimmed());

    // Print rows
    for row in rows {
        if let Some(row_arr) = row.as_array() {
            let row_str: String = row_arr
                .iter()
                .enumerate()
                .map(|(i, cell)| {
                    let cell_str = format_cell(cell);
                    let width = widths.get(i).copied().unwrap_or(10);
                    let char_count = cell_str.chars().count();
                    if char_count > width && width > 1 {
                        format!("{}…", cell_str.chars().take(width - 1).collect::<String>())
                    } else {
                        format!("{cell_str:width$}")
                    }
                })
                .collect::<Vec<_>>()
                .join("  ");
            println!("{row_str}");
        }
    }

    println!();
    println!("{} rows", rows.len().to_string().bold());

    Ok(())
}

fn print_summary(rows: &[Value], columns: &[Value]) -> Result<()> {
    println!(
        "{} rows × {} columns",
        rows.len().to_string().bold(),
        columns.len().to_string().bold()
    );
    println!();

    // Show column names
    println!("{}", "Columns:".dimmed());
    for col in columns {
        println!("  {}", col.as_str().unwrap_or("?"));
    }

    // Show first few rows as preview
    println!();
    println!("{}", "Preview (first 5 rows):".dimmed());
    for row in rows.iter().take(5) {
        if let Some(row_arr) = row.as_array() {
            let preview: String = row_arr
                .iter()
                .take(5)
                .map(format_cell)
                .collect::<Vec<_>>()
                .join(", ");
            println!("  {preview}");
        }
    }

    if rows.len() > 5 {
        let remaining = rows.len() - 5;
        println!("  {}", format!("... and {remaining} more rows").dimmed());
    }

    println!();
    println!(
        "{}",
        "Use --json for full output or --format table for tabular view".dimmed()
    );

    Ok(())
}

fn format_cell(value: &Value) -> String {
    match value {
        Value::Null => "null".to_string(),
        Value::Bool(b) => b.to_string(),
        Value::Number(n) => n.to_string(),
        Value::String(s) => s.clone(),
        Value::Array(arr) => format!("[{} items]", arr.len()),
        Value::Object(_) => "{...}".to_string(),
    }
}
