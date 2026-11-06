use anyhow::Result;
use colored::Colorize;

use crate::invocation_context::context;

use super::{data_freshness_seconds_to_schedule, fetch_endpoint, GetArgs};

pub fn get_endpoint(args: &GetArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_get");

    let endpoint = fetch_endpoint(&args.name, args.debug)?;

    // URLs prominently at the top
    crate::safe_println!();
    if let Some(ui_url) = &endpoint.ui_url {
        crate::safe_println!("  {}  {}", "View:".bold(), ui_url.cyan());
    }
    if let Some(url) = &endpoint.url {
        crate::safe_println!("  {}  {}", "Run:".bold(), url.cyan());
    }
    crate::safe_println!();

    // Name and status
    crate::safe_println!("  {}  {}", "Name:".bold(), endpoint.name);
    crate::safe_println!(
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
        crate::safe_println!("  {}  {}", "Description:".bold(), endpoint.description);
    }

    // Version info
    crate::safe_println!(
        "  {}  {} ({} total)",
        "Version:".bold(),
        endpoint.current_version,
        endpoint.versions_count
    );

    // Materialization
    crate::safe_println!();
    if endpoint.is_materialized {
        crate::safe_println!("  {}", "Materialization".bold().underline());
        if let Some(mat) = &endpoint.materialization {
            crate::safe_println!(
                "    Status: {}",
                match mat.status.as_deref() {
                    Some("Completed") => "completed".green(),
                    Some("Running") => "running".yellow(),
                    Some("Failed") => "failed".red(),
                    Some(s) => s.normal(),
                    None => "unknown".dimmed(),
                }
            );
            if let Some(seconds) = endpoint.data_freshness_seconds {
                if let Some(schedule) = data_freshness_seconds_to_schedule(seconds) {
                    crate::safe_println!("    Refresh: {schedule}");
                }
            }
            if let Some(last) = &mat.last_materialized_at {
                crate::safe_println!("    Last materialized: {last}");
            }
            if let Some(err) = &mat.error {
                crate::safe_println!("    Error: {}", err.red());
            }
        }
    } else {
        crate::safe_println!("  {}  disabled", "Materialization:".bold());
        if let Some(mat) = &endpoint.materialization {
            if !mat.can_materialize {
                if let Some(reason) = &mat.reason {
                    crate::safe_println!("    {}", reason.dimmed());
                }
            }
        }
    }

    // Query
    crate::safe_println!();
    crate::safe_println!("  {}", "Query".bold().underline());
    let query_str = if let Some(query) = endpoint.query.get("query").and_then(|q| q.as_str()) {
        query.to_string()
    } else {
        serde_json::to_string_pretty(&endpoint.query).unwrap_or_else(|_| "{}".to_string())
    };

    for line in query_str.lines() {
        crate::safe_println!("    {}", line.dimmed());
    }

    // Timestamps
    crate::safe_println!();
    crate::safe_println!("  Created: {}", endpoint.created_at.dimmed());
    crate::safe_println!("  Updated: {}", endpoint.updated_at.dimmed());

    crate::safe_println!();

    Ok(())
}
