use anyhow::Result;
use colored::Colorize;

use crate::invocation_context::context;

use super::{fetch_endpoint, GetArgs};

pub fn get_endpoint(args: &GetArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_get");

    let endpoint = fetch_endpoint(&args.name, args.debug)?;

    // URLs prominently at the top
    println!();
    if let Some(ui_url) = &endpoint.ui_url {
        println!("  {}  {}", "View:".bold(), ui_url.cyan());
    }
    if let Some(url) = &endpoint.url {
        println!("  {}  {}", "Run:".bold(), url.cyan());
    }
    println!();

    // Name and status
    println!("  {}  {}", "Name:".bold(), endpoint.name);
    println!(
        "  {}  {}",
        "Status:".bold(),
        if endpoint.is_active {
            "active".green()
        } else {
            "inactive".red()
        }
    );

    // Description
    if !endpoint.description.is_empty() {
        println!("  {}  {}", "Description:".bold(), endpoint.description);
    }

    // Version info
    println!(
        "  {}  {} ({} total)",
        "Version:".bold(),
        endpoint.current_version,
        endpoint.versions_count
    );

    // Materialization
    println!();
    if endpoint.is_materialized {
        println!("  {}", "Materialization".bold().underline());
        if let Some(mat) = &endpoint.materialization {
            println!(
                "    Status: {}",
                match mat.status.as_deref() {
                    Some("Completed") => "completed".green(),
                    Some("Running") => "running".yellow(),
                    Some("Failed") => "failed".red(),
                    Some(s) => s.normal(),
                    None => "unknown".dimmed(),
                }
            );
            if let Some(freq) = &mat.sync_frequency {
                println!("    Sync frequency: {freq}");
            }
            if let Some(last) = &mat.last_materialized_at {
                println!("    Last materialized: {last}");
            }
            if let Some(err) = &mat.error {
                println!("    Error: {}", err.red());
            }
        }
    } else {
        println!("  {}  disabled", "Materialization:".bold());
        if let Some(mat) = &endpoint.materialization {
            if !mat.can_materialize {
                if let Some(reason) = &mat.reason {
                    println!("    {}", reason.dimmed());
                }
            }
        }
    }

    // Query
    println!();
    println!("  {}", "Query".bold().underline());
    let query_str = if let Some(query) = endpoint.query.get("query").and_then(|q| q.as_str()) {
        query.to_string()
    } else {
        serde_json::to_string_pretty(&endpoint.query).unwrap_or_else(|_| "{}".to_string())
    };

    for line in query_str.lines() {
        println!("    {}", line.dimmed());
    }

    // Timestamps
    println!();
    println!("  Created: {}", endpoint.created_at.dimmed());
    println!("  Updated: {}", endpoint.updated_at.dimmed());

    println!();

    Ok(())
}
