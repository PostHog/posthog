use anyhow::{Context, Result};
use clap::Args;
use posthog_rs::{ClientOptionsBuilder, Event};
use serde_json::Value;
use std::collections::HashMap;
use tracing::info;

use crate::invocation_context::context;

#[derive(Args, Debug)]
pub struct CaptureArgs {
    /// The name of the event to capture
    #[arg(short, long)]
    pub event: String,

    /// The distinct ID of the user. If not provided, an anonymous event will be captured
    #[arg(short, long)]
    pub distinct_id: Option<String>,

    /// Event properties as JSON string (e.g. '{"key": "value"}')
    #[arg(short, long)]
    pub properties: Option<String>,

    /// Event properties as key=value pairs (can be used multiple times)
    #[arg(short = 'P', long = "property")]
    pub property_pairs: Option<Vec<String>>,
}

pub fn capture_event(args: &CaptureArgs) -> Result<()> {
    info!("Capturing event: {}", args.event);

    let ctx = context();
    let client = &ctx.client;
    let project_api_key = client
        .get_project_api_key()
        .context("Failed to get project API key")?;

    let ingest_url = client.build_ingest_url()?;

    let client_options = ClientOptionsBuilder::default()
        .api_key(project_api_key)
        .api_endpoint(ingest_url.to_string())
        .build()
        .context("Failed to build posthog client")?;

    let posthog_client = posthog_rs::client(client_options);

    // Create event based on whether distinct_id is provided
    let mut event = if let Some(distinct_id) = &args.distinct_id {
        Event::new(&args.event, distinct_id)
    } else {
        Event::new_anon(args.event.clone())
    };

    // Parse and add properties
    let mut properties: HashMap<String, Value> = HashMap::new();

    // Add properties from JSON string if provided
    if let Some(props_json) = &args.properties {
        let parsed: HashMap<String, Value> = serde_json::from_str(props_json)
            .context("Failed to parse properties JSON. Expected format: '{\"key\": \"value\"}'")?;
        properties.extend(parsed);
    }

    // Add properties from key=value pairs if provided
    if let Some(pairs) = &args.property_pairs {
        for pair in pairs {
            let parts: Vec<&str> = pair.splitn(2, '=').collect();
            if parts.len() != 2 {
                anyhow::bail!("Invalid property format: '{pair}'. Expected format: key=value",);
            }

            let key = parts[0].to_string();
            let value_str = parts[1];

            // Try to parse as JSON value, fallback to string
            let value = serde_json::from_str::<Value>(value_str).unwrap_or_else(|_| {
                // If parsing as JSON fails, treat as string
                Value::String(value_str.to_string())
            });

            properties.insert(key, value);
        }
    }

    // Insert all properties into the event
    for (key, value) in properties {
        event
            .insert_prop(&key, value)
            .map_err(|e| anyhow::anyhow!("Failed to insert property '{key}': {e:?}"))?;
    }

    info!("Event properties: {:?}", event);

    // Capture the event
    posthog_client
        .capture(event)
        .map_err(|e| anyhow::anyhow!("Failed to capture event to PostHog: {e:?}"))?;

    println!("Event '{}' captured successfully!", args.event);

    Ok(())
}
