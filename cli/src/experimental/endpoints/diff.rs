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
        crate::safe_println!("No endpoint YAML files found in the specified paths.");
        return Ok(());
    }

    // Parse local endpoints
    let local_endpoints: Vec<EndpointYaml> = yaml_files
        .iter()
        .filter_map(
            |(path, content)| match serde_yaml::from_str::<EndpointYaml>(content) {
                Ok(endpoint) => Some(endpoint),
                Err(e) => {
                    crate::safe_eprintln!("{} Failed to parse {}: {}", "⚠".yellow(), path, e);
                    None
                }
            },
        )
        .collect();

    if local_endpoints.is_empty() {
        crate::safe_println!("No valid endpoint YAML files found.");
        return Ok(());
    }

    // Fetch remote endpoints
    let remote_list = fetch_all_endpoints(args.debug)?;
    let remote_map: HashMap<&str, &EndpointResponse> = remote_list
        .results
        .iter()
        .map(|e| (e.name.as_str(), e))
        .collect();

    crate::safe_println!();

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
                    crate::safe_println!("  {}  {}", "SAME".dimmed(), local.name);
                }
            } else {
                changed_count += 1;
                has_differences = true;
                crate::safe_println!("  {}  {}", "CHANGED".yellow().bold(), local.name.bold());
                for change in &changes {
                    print_change_with_labels(change);
                }
                crate::safe_println!();
            }
        } else {
            new_count += 1;
            has_differences = true;
            crate::safe_println!(
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
                    crate::safe_println!("    {}", truncated.dimmed());
                }
            }
            crate::safe_println!();
        }
    }

    // Summary
    crate::safe_println!(
        "{} file{} compared: {} new, {} changed, {} unchanged",
        local_endpoints.len(),
        if local_endpoints.len() == 1 { "" } else { "s" },
        new_count,
        changed_count,
        unchanged_count
    );

    if has_differences {
        crate::safe_println!();
        crate::safe_println!(
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
            crate::safe_eprintln!("{} Path not found: {}", "⚠".yellow(), path_str);
        }
    }

    Ok(files)
}

/// Print a change with clear local/remote labels
fn print_change_with_labels(change: &Change) {
    match change {
        Change::Description { from, to } => {
            crate::safe_println!("    {}:", "Description".bold());
            crate::safe_println!(
                "      {} {}",
                "remote:".cyan(),
                if from.is_empty() {
                    "(empty)".dimmed().to_string()
                } else {
                    from.clone()
                }
            );
            crate::safe_println!(
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
            crate::safe_println!("    {}:", "Query".bold());
            crate::safe_println!("      {} {}", "---".red(), "remote (PostHog)".red());
            crate::safe_println!("      {} {}", "+++".green(), "local (YAML)".green());
            print_diff(from, to, "      ");
        }
        Change::QueryDefinition { from, to } => {
            crate::safe_println!("    {}:", "Query definition".bold());
            crate::safe_println!("      {} {}", "---".red(), "remote (PostHog)".red());
            crate::safe_println!("      {} {}", "+++".green(), "local (YAML)".green());
            print_diff(from, to, "      ");
        }
        Change::Materialization { from, to } => {
            crate::safe_println!("    {}:", "Materialization".bold());
            crate::safe_println!(
                "      {} {}",
                "remote:".cyan(),
                if *from { "enabled" } else { "disabled" }
            );
            crate::safe_println!(
                "      {}  {}",
                "local:".green(),
                if *to { "enabled" } else { "disabled" }
            );
        }
        Change::Schedule { from, to } => {
            crate::safe_println!("    {}:", "Schedule".bold());
            crate::safe_println!(
                "      {} {}",
                "remote:".cyan(),
                if from.is_empty() {
                    "(none)"
                } else {
                    from.as_str()
                }
            );
            crate::safe_println!(
                "      {}  {}",
                "local:".green(),
                if to.is_empty() { "(none)" } else { to.as_str() }
            );
        }
        Change::Variables { from, to } => {
            crate::safe_println!("    {}:", "Variables".bold());
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
            crate::safe_println!("      {} [{}]", "remote:".cyan(), from_str);
            crate::safe_println!("      {}  [{}]", "local:".green(), to_str);
        }
    }
}
