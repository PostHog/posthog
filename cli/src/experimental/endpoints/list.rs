use anyhow::Result;
use colored::Colorize;

use crate::invocation_context::context;

use super::{data_freshness_seconds_to_schedule, fetch_all_endpoints, EndpointResponse, ListArgs};

pub fn list_endpoints(args: &ListArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_list");

    let client = &context().client;
    let env_id = client.get_env_id();

    println!();
    println!("Fetching endpoints from PostHog...");
    println!();

    let endpoint_list = fetch_all_endpoints(args.debug)?;

    if endpoint_list.results.is_empty() {
        println!("No endpoints found in project {env_id}.");
        println!();
        println!("Create an endpoint by pushing a YAML file:");
        println!("  posthog-cli exp endpoints push my-endpoint.yaml");
        return Ok(());
    }

    println!("Endpoints in project {}:", env_id.bold());
    println!();

    for endpoint in &endpoint_list.results {
        print_endpoint_summary(endpoint);
    }

    println!();
    println!(
        "{} endpoint{} total.",
        endpoint_list.results.len(),
        if endpoint_list.results.len() == 1 {
            ""
        } else {
            "s"
        }
    );

    Ok(())
}

fn print_endpoint_summary(endpoint: &EndpointResponse) {
    let status = if endpoint.is_materialized {
        let schedule = endpoint
            .data_freshness_seconds
            .and_then(data_freshness_seconds_to_schedule)
            .map(format_sync_frequency)
            .unwrap_or_else(|| "scheduled".to_string());
        format!("Materialized ({schedule})").green().to_string()
    } else {
        "On-demand".yellow().to_string()
    };

    let active_status = if endpoint.is_active {
        ""
    } else {
        " [inactive]"
    };

    println!(
        "  {:<28} {}{}",
        endpoint.name.bold(),
        status,
        active_status.dimmed()
    );

    if !endpoint.description.is_empty() {
        let desc = if endpoint.description.len() > 60 {
            format!("{}...", &endpoint.description[..57])
        } else {
            endpoint.description.clone()
        };
        println!("    {}", desc.dimmed());
    }
}

/// Format a bucket schedule string for display.
fn format_sync_frequency(freq: &str) -> String {
    match freq {
        "15min" => "every 15 min".to_string(),
        "30min" => "every 30 min".to_string(),
        "1hour" => "hourly".to_string(),
        "6hour" => "every 6 hours".to_string(),
        "12hour" => "every 12 hours".to_string(),
        "24hour" => "daily".to_string(),
        "7day" => "weekly".to_string(),
        _ => freq.to_string(),
    }
}
