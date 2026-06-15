use std::collections::HashMap;
use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use colored::Colorize;

use crate::invocation_context::context;

use super::{
    compute_changes_for_push, fetch_all_endpoints, print_diff, Change, DiffArgs, EndpointResponse,
    EndpointYaml,
};

pub fn diff_endpoints(args: &DiffArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_diff");

    // Collect all YAML files from the provided paths
    let yaml_files = collect_yaml_files(&args.paths)?;

    if yaml_files.is_empty() {
        println!("No endpoint YAML files found in the specified paths.");
        return Ok(());
    }

    // Parse local endpoints
    let local_endpoints: Vec<EndpointYaml> = yaml_files
        .iter()
        .filter_map(
            |(path, content)| match serde_yaml::from_str::<EndpointYaml>(content) {
                Ok(endpoint) => Some(endpoint),
                Err(e) => {
                    eprintln!("{} Failed to parse {}: {}", "⚠".yellow(), path, e);
                    None
                }
            },
        )
        .collect();

    if local_endpoints.is_empty() {
        println!("No valid endpoint YAML files found.");
        return Ok(());
    }

    // Fetch remote endpoints
    let remote_list = fetch_all_endpoints(args.debug)?;
    let remote_map: HashMap<&str, &EndpointResponse> = remote_list
        .results
        .iter()
        .map(|e| (e.name.as_str(), e))
        .collect();

    println!();

    let mut has_differences = false;
    let mut new_count = 0;
    let mut changed_count = 0;
    let mut unchanged_count = 0;

    for local in &local_endpoints {
        if let Some(remote) = remote_map.get(local.name.as_str()) {
            let changes = compute_changes_for_push(local, remote);
            if changes.is_empty() {
                unchanged_count += 1;
                if args.verbose {
                    println!("  {}  {}", "SAME".dimmed(), local.name);
                }
            } else {
                changed_count += 1;
                has_differences = true;
                println!("  {}  {}", "CHANGED".yellow().bold(), local.name.bold());
                for change in &changes {
                    print_change_with_labels(change);
                }
                println!();
            }
        } else {
            new_count += 1;
            has_differences = true;
            println!(
                "  {}  {} (not in PostHog)",
                "NEW".green().bold(),
                local.name.bold()
            );
            if let Some(desc) = &local.description {
                if !desc.is_empty() {
                    let truncated: String = if desc.chars().count() > 60 {
                        format!("{}...", desc.chars().take(57).collect::<String>())
                    } else {
                        desc.clone()
                    };
                    println!("    {}", truncated.dimmed());
                }
            }
            println!();
        }
    }

    // Summary
    println!(
        "{} file{} compared: {} new, {} changed, {} unchanged",
        local_endpoints.len(),
        if local_endpoints.len() == 1 { "" } else { "s" },
        new_count,
        changed_count,
        unchanged_count
    );

    if has_differences {
        println!();
        println!(
            "{}",
            "Run 'posthog-cli exp endpoints push <path>' to apply changes.".dimmed()
        );
    }

    Ok(())
}

/// Collect all YAML files from the provided paths (files or directories)
fn collect_yaml_files(paths: &[String]) -> Result<Vec<(String, String)>> {
    let mut files = Vec::new();

    for path_str in paths {
        let path = Path::new(path_str);

        if path.is_file() {
            let content = fs::read_to_string(path)
                .with_context(|| format!("Failed to read file: {path_str:?}"))?;
            files.push((path_str.clone(), content));
        } else if path.is_dir() {
            for entry in fs::read_dir(path)
                .with_context(|| format!("Failed to read directory: {path_str:?}"))?
            {
                let entry = entry?;
                let entry_path = entry.path();

                if entry_path.is_file() {
                    if let Some(ext) = entry_path.extension() {
                        if ext == "yaml" || ext == "yml" {
                            let content = fs::read_to_string(&entry_path).with_context(|| {
                                format!("Failed to read: {}", entry_path.display())
                            })?;
                            files.push((entry_path.display().to_string(), content));
                        }
                    }
                }
            }
        } else {
            eprintln!("{} Path not found: {}", "⚠".yellow(), path_str);
        }
    }

    Ok(files)
}

/// Print a change with clear local/remote labels
fn print_change_with_labels(change: &Change) {
    match change {
        Change::Description { from, to } => {
            println!("    {}:", "Description".bold());
            println!(
                "      {} {}",
                "remote:".cyan(),
                if from.is_empty() {
                    "(empty)".dimmed().to_string()
                } else {
                    from.clone()
                }
            );
            println!(
                "      {}  {}",
                "local:".green(),
                if to.is_empty() {
                    "(empty)".dimmed().to_string()
                } else {
                    to.clone()
                }
            );
        }
        Change::Query { from, to } => {
            println!("    {}:", "Query".bold());
            println!("      {} {}", "---".red(), "remote (PostHog)".red());
            println!("      {} {}", "+++".green(), "local (YAML)".green());
            print_diff(from, to, "      ");
        }
        Change::QueryDefinition { from, to } => {
            println!("    {}:", "Query definition".bold());
            println!("      {} {}", "---".red(), "remote (PostHog)".red());
            println!("      {} {}", "+++".green(), "local (YAML)".green());
            print_diff(from, to, "      ");
        }
        Change::Materialization { from, to } => {
            println!("    {}:", "Materialization".bold());
            println!(
                "      {} {}",
                "remote:".cyan(),
                if *from { "enabled" } else { "disabled" }
            );
            println!(
                "      {}  {}",
                "local:".green(),
                if *to { "enabled" } else { "disabled" }
            );
        }
        Change::Schedule { from, to } => {
            println!("    {}:", "Schedule".bold());
            println!(
                "      {} {}",
                "remote:".cyan(),
                if from.is_empty() {
                    "(none)"
                } else {
                    from.as_str()
                }
            );
            println!(
                "      {}  {}",
                "local:".green(),
                if to.is_empty() { "(none)" } else { to.as_str() }
            );
        }
        Change::Variables { from, to } => {
            println!("    {}:", "Variables".bold());
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
            println!("      {} [{}]", "remote:".cyan(), from_str);
            println!("      {}  [{}]", "local:".green(), to_str);
        }
    }
}
