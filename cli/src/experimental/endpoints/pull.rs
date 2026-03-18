use std::collections::HashMap;
use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use colored::Colorize;
use inquire::Confirm;

use crate::invocation_context::context;

use super::{
    fetch_all_endpoints, format_change_summary, get_local_schedule, get_remote_schedule,
    get_remote_variable_names, print_diff, Change, EndpointResponse, EndpointYaml, PullArgs,
};

#[derive(Debug)]
enum PullAction {
    Create {
        endpoint: EndpointResponse,
        file_path: String,
    },
    Update {
        endpoint: EndpointResponse,
        file_path: String,
        changes: Vec<Change>,
    },
    Skip {
        name: String,
        reason: String,
    },
}

/// Check if a path looks like a YAML file path (ends in .yaml or .yml)
fn is_yaml_file_path(path: &str) -> bool {
    let lower = path.to_lowercase();
    lower.ends_with(".yaml") || lower.ends_with(".yml")
}

pub fn pull_endpoints(args: &PullArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_pull");

    println!();
    println!("Fetching endpoints from PostHog...");
    println!();

    // Fetch all remote endpoints
    let remote_list = fetch_all_endpoints(args.debug)?;

    if remote_list.results.is_empty() {
        println!("No endpoints found in PostHog.");
        return Ok(());
    }

    // Check if output is a file path (for single endpoint output)
    let output_is_file = is_yaml_file_path(&args.output);

    // Determine which endpoints to pull
    let endpoints_to_pull: Vec<&EndpointResponse> = if args.all {
        remote_list.results.iter().collect()
    } else if !args.names.is_empty() {
        let name_set: std::collections::HashSet<_> = args.names.iter().collect();
        let found: Vec<_> = remote_list
            .results
            .iter()
            .filter(|e| name_set.contains(&e.name))
            .collect();

        // Check for missing endpoints
        for name in &args.names {
            if !remote_list.results.iter().any(|e| &e.name == name) {
                println!("{} Endpoint '{}' not found in PostHog", "⚠".yellow(), name);
            }
        }

        if found.is_empty() {
            println!("No matching endpoints found.");
            return Ok(());
        }

        found
    } else {
        println!("Specify endpoint name(s) to pull, or use --all to pull all endpoints.");
        println!();
        println!("Usage:");
        println!("  posthog-cli exp endpoints pull <name>...");
        println!("  posthog-cli exp endpoints pull --all");
        return Ok(());
    };

    // If output is a file path, only allow pulling a single endpoint
    if output_is_file && endpoints_to_pull.len() > 1 {
        anyhow::bail!(
            "Cannot write {} endpoints to a single file. Use a directory path or pull one endpoint at a time.",
            endpoints_to_pull.len()
        );
    }

    // Read existing local files to compare (only for directory mode)
    let output_path = Path::new(&args.output);
    let local_files = if output_is_file {
        // For file mode, check if the target file exists and parse it
        if output_path.exists() {
            let content = fs::read_to_string(output_path)?;
            match serde_yaml::from_str::<EndpointYaml>(&content) {
                Ok(endpoint) => {
                    let mut map = HashMap::new();
                    map.insert(endpoint.name.clone(), endpoint);
                    map
                }
                Err(_) => HashMap::new(),
            }
        } else {
            HashMap::new()
        }
    } else {
        read_local_endpoints(output_path)?
    };

    // Determine actions for each endpoint
    let actions: Vec<PullAction> = endpoints_to_pull
        .into_iter()
        .map(|remote| {
            // In file mode, use the exact path; in directory mode, construct {dir}/{name}.yaml
            let file_path = if output_is_file {
                args.output.clone()
            } else {
                output_path
                    .join(format!("{}.yaml", remote.name))
                    .display()
                    .to_string()
            };

            if let Some(local) = local_files.get(&remote.name) {
                let changes = compute_changes_from_remote(remote, local);
                if changes.is_empty() {
                    PullAction::Skip {
                        name: remote.name.clone(),
                        reason: "No changes".to_string(),
                    }
                } else {
                    PullAction::Update {
                        endpoint: remote.clone(),
                        file_path,
                        changes,
                    }
                }
            } else {
                PullAction::Create {
                    endpoint: remote.clone(),
                    file_path,
                }
            }
        })
        .collect();

    // Count actions
    let creates: Vec<_> = actions
        .iter()
        .filter(|a| matches!(a, PullAction::Create { .. }))
        .collect();
    let updates: Vec<_> = actions
        .iter()
        .filter(|a| matches!(a, PullAction::Update { .. }))
        .collect();
    let skips: Vec<_> = actions
        .iter()
        .filter(|a| matches!(a, PullAction::Skip { .. }))
        .collect();

    if creates.is_empty() && updates.is_empty() {
        println!("No changes to write.");
        for skip in &skips {
            if let PullAction::Skip { name, reason, .. } = skip {
                println!("  {} {} ({})", "SKIP".dimmed(), name, reason.dimmed());
            }
        }
        return Ok(());
    }

    // Display preview
    println!("Files to write:");
    println!();

    for action in &actions {
        match action {
            PullAction::Create {
                endpoint,
                file_path,
            } => {
                println!("  {}  {}", "CREATE".green().bold(), file_path.bold());
                println!("    New file (endpoint not in local directory)");
                if !endpoint.description.is_empty() {
                    let desc = if endpoint.description.chars().count() > 50 {
                        format!(
                            "{}...",
                            endpoint.description.chars().take(47).collect::<String>()
                        )
                    } else {
                        endpoint.description.clone()
                    };
                    println!("    Description: {}", desc.dimmed());
                }
                println!();
            }
            PullAction::Update {
                file_path, changes, ..
            } => {
                println!("  {}  {}", "UPDATE".yellow().bold(), file_path.bold());
                for change in changes {
                    println!("    - {}", format_change_summary(change));
                    if let Change::Query { from, to } = change {
                        print_diff(from, to, "      ");
                    }
                }
                println!();
            }
            PullAction::Skip { name, reason, .. } => {
                println!(
                    "  {}    {}.yaml ({})",
                    "SKIP".dimmed(),
                    name,
                    reason.dimmed()
                );
            }
        }
    }

    // If dry-run, stop here
    if args.dry_run {
        println!();
        println!("{}", "(dry-run mode, no files written)".dimmed());
        return Ok(());
    }

    // Confirm unless --yes
    let change_count = creates.len() + updates.len();
    if !args.yes {
        let confirm = Confirm::new(&format!(
            "Write {} file{}?",
            change_count,
            if change_count == 1 { "" } else { "s" }
        ))
        .with_default(true)
        .prompt();

        match confirm {
            Ok(true) => {}
            Ok(false) => {
                println!("Cancelled.");
                return Ok(());
            }
            Err(_) => {
                println!("Cancelled.");
                return Ok(());
            }
        }
    }

    println!();

    // Ensure output directory exists
    if output_is_file {
        // For file mode, ensure the parent directory exists
        if let Some(parent) = output_path.parent() {
            if !parent.as_os_str().is_empty() && !parent.exists() {
                fs::create_dir_all(parent)
                    .with_context(|| format!("Failed to create directory: {}", parent.display()))?;
            }
        }
    } else if !output_path.exists() {
        fs::create_dir_all(output_path)
            .with_context(|| format!("Failed to create directory: {}", args.output))?;
    }

    // Write files
    let mut success_count = 0;

    for action in actions {
        match action {
            PullAction::Create {
                endpoint,
                file_path,
            } => {
                let yaml = EndpointYaml::from_api_response(&endpoint);
                match write_yaml_file(&file_path, &yaml) {
                    Ok(()) => {
                        println!("{} Created: {}", "✓".green(), file_path);
                        success_count += 1;
                    }
                    Err(e) => {
                        println!("{} Failed to write {}: {}", "✗".red(), file_path, e);
                    }
                }
            }
            PullAction::Update {
                endpoint,
                file_path,
                ..
            } => {
                let yaml = EndpointYaml::from_api_response(&endpoint);
                match write_yaml_file(&file_path, &yaml) {
                    Ok(()) => {
                        println!("{} Updated: {}", "✓".green(), file_path);
                        success_count += 1;
                    }
                    Err(e) => {
                        println!("{} Failed to write {}: {}", "✗".red(), file_path, e);
                    }
                }
            }
            PullAction::Skip { .. } => {}
        }
    }

    println!();
    println!(
        "{} file{} written.",
        success_count,
        if success_count == 1 { "" } else { "s" }
    );

    Ok(())
}

/// Read existing local endpoint YAML files from a directory
fn read_local_endpoints(dir: &Path) -> Result<HashMap<String, EndpointYaml>> {
    let mut endpoints = HashMap::new();

    if !dir.exists() {
        return Ok(endpoints);
    }

    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();

        if path.is_file() {
            if let Some(ext) = path.extension() {
                if ext == "yaml" || ext == "yml" {
                    let content = fs::read_to_string(&path)?;
                    match serde_yaml::from_str::<EndpointYaml>(&content) {
                        Ok(endpoint) => {
                            endpoints.insert(endpoint.name.clone(), endpoint);
                        }
                        Err(_) => {
                            // Skip files that don't parse as endpoints
                        }
                    }
                }
            }
        }
    }

    Ok(endpoints)
}

/// Compute changes between a remote endpoint and a local YAML file (pull direction).
/// Returns changes where `from` is the local state and `to` is the remote state.
fn compute_changes_from_remote(remote: &EndpointResponse, local: &EndpointYaml) -> Vec<Change> {
    let mut changes = Vec::new();

    // Description
    let local_desc = local.description.as_deref().unwrap_or("");
    if remote.description != local_desc {
        changes.push(Change::Description {
            from: local_desc.to_string(),
            to: remote.description.clone(),
        });
    }

    // Query
    let remote_query = remote
        .query
        .get("query")
        .and_then(|q| q.as_str())
        .unwrap_or("");
    let local_query = local.query.as_deref().unwrap_or("");
    if !remote_query.is_empty() && remote_query != local_query {
        changes.push(Change::Query {
            from: local_query.to_string(),
            to: remote_query.to_string(),
        });
    }

    // Materialization
    let local_mat = local
        .materialization
        .as_ref()
        .map(|m| m.enabled)
        .unwrap_or(false);
    if remote.is_materialized != local_mat {
        changes.push(Change::Materialization {
            from: local_mat,
            to: remote.is_materialized,
        });
    }

    // Schedule
    let local_schedule = get_local_schedule(local);
    let remote_schedule = get_remote_schedule(remote);
    if local_schedule != remote_schedule {
        changes.push(Change::Schedule {
            from: local_schedule,
            to: remote_schedule,
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
            from: local_vars,
            to: remote_vars,
        });
    }

    changes
}

/// Write an EndpointYaml to a file
fn write_yaml_file(path: &str, endpoint: &EndpointYaml) -> Result<()> {
    let yaml_content =
        serde_yaml::to_string(endpoint).context("Failed to serialize endpoint to YAML")?;

    // Add a header comment
    let content = format!("# {}.yaml\n{}", endpoint.name, yaml_content);

    fs::write(path, content).with_context(|| format!("Failed to write file: {path}"))
}
