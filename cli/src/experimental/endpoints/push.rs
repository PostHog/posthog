use std::collections::HashMap;
use std::fs;
use std::path::Path;

use anyhow::{Context, Result};
use colored::Colorize;
use inquire::Confirm;

use crate::invocation_context::context;

use super::{
    compute_changes_for_push, create_insight_variable, fetch_all_endpoints,
    fetch_insight_variables, format_change_summary, get_remote_variable_names, print_diff, Change,
    CreateInsightVariableRequest, EndpointResponse, EndpointVariable, EndpointYaml,
    InsightVariable, PushArgs, ResolvedVariables, VALID_SYNC_FREQUENCIES,
};

/// Represents a variable change for display in the diff
#[derive(Debug, Clone)]
pub enum VariableChange {
    Create(EndpointVariable),
    Update {
        code_name: String,
        from_type: String,
        to_type: String,
    },
    Remove(String), // code_name being removed
}

#[derive(Debug)]
enum PushAction {
    Create {
        endpoint: EndpointYaml,
        variable_changes: Vec<VariableChange>,
    },
    Update {
        local: EndpointYaml,
        changes: Vec<Change>,
        variable_changes: Vec<VariableChange>,
    },
    Skip {
        name: String,
        reason: String,
    },
}

/// Push local YAML files to PostHog
pub fn push_endpoints(args: &PushArgs) -> Result<()> {
    context().capture_command_invoked("endpoints_push");

    // 1. Collect and parse all YAML files
    let yaml_files = collect_yaml_files(&args.paths)?;

    if yaml_files.is_empty() {
        println!("No YAML files found in the specified paths.");
        return Ok(());
    }

    // 2. Parse YAML files into endpoint definitions
    let mut endpoints: Vec<EndpointYaml> = Vec::new();
    for (path, content) in &yaml_files {
        match parse_yaml_file(path, content) {
            Ok(endpoint) => {
                if let Err(e) = endpoint.validate() {
                    println!("{} Skipping {}: {}", "⚠".yellow(), path, e);
                    continue;
                }
                endpoints.push(endpoint);
            }
            Err(e) => {
                println!("{} Failed to parse {}: {}", "✗".red(), path, e);
            }
        }
    }

    if endpoints.is_empty() {
        println!("No valid endpoints found to push.");
        return Ok(());
    }

    println!();
    println!("Comparing local files with PostHog...");
    println!();

    // 3. Fetch remote endpoints and insight variables
    let remote_list = fetch_all_endpoints(args.debug)?;
    let remote_by_name: HashMap<String, EndpointResponse> = remote_list
        .results
        .into_iter()
        .map(|e| (e.name.clone(), e))
        .collect();

    let existing_variables = fetch_insight_variables(args.debug)?;
    let vars_by_code_name: HashMap<String, InsightVariable> = existing_variables
        .into_iter()
        .map(|v| (v.code_name.clone(), v))
        .collect();

    // 4. Determine actions for each endpoint
    let mut actions: Vec<PushAction> = Vec::new();

    for local in endpoints {
        // Compute variable changes
        let remote_vars = remote_by_name
            .get(&local.name)
            .map(get_remote_variable_names)
            .unwrap_or_default();

        let local_vars: Vec<String> = local
            .variables
            .as_ref()
            .map(|v| v.iter().map(|var| var.name.clone()).collect())
            .unwrap_or_default();

        // Check for variables being removed
        let removed_vars: Vec<String> = remote_vars
            .iter()
            .filter(|v| !local_vars.contains(v))
            .cloned()
            .collect();

        // Validate that removed variables aren't still referenced in query
        let query_refs = local.get_variable_references();
        let still_referenced: Vec<&String> = removed_vars
            .iter()
            .filter(|v| query_refs.contains(v))
            .collect();

        if !still_referenced.is_empty() {
            actions.push(PushAction::Skip {
                name: local.name.clone(),
                reason: format!(
                    "Query still references removed variable(s): {}",
                    still_referenced
                        .iter()
                        .map(|s| s.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                ),
            });
            continue;
        }

        // Validate that all defined variables are actually used in the query
        let unused_vars: Vec<&String> = local_vars
            .iter()
            .filter(|v| !query_refs.contains(v))
            .collect();

        if !unused_vars.is_empty() {
            actions.push(PushAction::Skip {
                name: local.name.clone(),
                reason: format!(
                    "Variable(s) defined but not used in query: {}. Remove from 'variables' in YAML.",
                    unused_vars
                        .iter()
                        .map(|s| s.as_str())
                        .collect::<Vec<_>>()
                        .join(", ")
                ),
            });
            continue;
        }

        // Validate schedule if materialization is enabled
        if let Some(mat) = &local.materialization {
            if mat.enabled {
                if let Some(schedule) = &mat.schedule {
                    if !VALID_SYNC_FREQUENCIES.contains(&schedule.as_str()) {
                        actions.push(PushAction::Skip {
                            name: local.name.clone(),
                            reason: format!(
                                "Invalid schedule '{}'. Valid options: {}",
                                schedule,
                                VALID_SYNC_FREQUENCIES.join(", ")
                            ),
                        });
                        continue;
                    }
                }
            }
        }

        // Compute variable changes for display
        let variable_changes = compute_variable_changes(&local, &remote_vars, &vars_by_code_name);

        if let Some(remote) = remote_by_name.get(&local.name) {
            let changes = compute_changes_for_push(&local, remote);
            if changes.is_empty() && variable_changes.is_empty() {
                actions.push(PushAction::Skip {
                    name: local.name.clone(),
                    reason: "No changes".to_string(),
                });
            } else {
                actions.push(PushAction::Update {
                    local,
                    changes,
                    variable_changes,
                });
            }
        } else {
            actions.push(PushAction::Create {
                endpoint: local,
                variable_changes,
            });
        }
    }

    // Count actions
    let creates: Vec<_> = actions
        .iter()
        .filter(|a| matches!(a, PushAction::Create { .. }))
        .collect();
    let updates: Vec<_> = actions
        .iter()
        .filter(|a| matches!(a, PushAction::Update { .. }))
        .collect();
    let skips: Vec<_> = actions
        .iter()
        .filter(|a| matches!(a, PushAction::Skip { .. }))
        .collect();

    if creates.is_empty() && updates.is_empty() {
        println!("No changes to apply.");
        for skip in &skips {
            if let PushAction::Skip { name, reason } = skip {
                println!("  {} {} ({})", "SKIP".dimmed(), name, reason.dimmed());
            }
        }
        return Ok(());
    }

    // 5. Display preview
    println!("Changes to apply:");
    println!();

    for action in &actions {
        match action {
            PushAction::Create {
                endpoint,
                variable_changes,
            } => {
                println!("  {}  {}", "CREATE".green().bold(), endpoint.name.bold());
                if let Some(desc) = &endpoint.description {
                    println!("    Description: {}", desc.dimmed());
                }
                print_query_preview(endpoint);
                print_variable_changes(variable_changes);
                if let Some(mat) = &endpoint.materialization {
                    if mat.enabled {
                        let schedule = mat.schedule.as_deref().unwrap_or("default");
                        println!("    Materialization: {schedule}");
                    }
                }
                println!();
            }
            PushAction::Update {
                local,
                changes,
                variable_changes,
            } => {
                println!("  {}  {}", "UPDATE".yellow().bold(), local.name.bold());
                for change in changes {
                    println!("    - {}", format_change_summary(change));
                    match change {
                        Change::Query { from, to } | Change::QueryDefinition { from, to } => {
                            print_diff(from, to, "      ");
                        }
                        _ => {}
                    }
                }
                print_variable_changes(variable_changes);
                println!();
            }
            PushAction::Skip { name, reason } => {
                println!("  {}    {} ({})", "SKIP".dimmed(), name, reason.dimmed());
            }
        }
    }

    // 6. If dry-run, stop here
    if args.dry_run {
        println!();
        println!("{}", "(dry-run mode, no changes applied)".dimmed());
        return Ok(());
    }

    // 7. Confirm unless --yes
    if !args.yes {
        let confirm = Confirm::new("Apply these changes?")
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

    // 8. Apply changes
    let mut success_count = 0;
    // Keep a mutable copy of vars_by_code_name to track newly created variables
    let mut vars_by_code_name = vars_by_code_name;

    for action in actions {
        match action {
            PushAction::Create {
                endpoint,
                variable_changes,
            } => {
                // Create any new variables first
                let resolved = match resolve_variables(
                    &endpoint,
                    &variable_changes,
                    &mut vars_by_code_name,
                    args.debug,
                ) {
                    Ok(r) => r,
                    Err(e) => {
                        println!(
                            "{} Failed to resolve variables for {}: {}",
                            "✗".red(),
                            endpoint.name,
                            e
                        );
                        continue;
                    }
                };

                match create_endpoint(&endpoint, &resolved, args.debug) {
                    Ok(created) => {
                        println!("{} Created: {}", "✓".green(), endpoint.name.bold());
                        if let Some(ui_url) = &created.ui_url {
                            println!("  {ui_url}");
                        }
                        success_count += 1;
                    }
                    Err(e) => {
                        println!("{} Failed to create {}: {}", "✗".red(), endpoint.name, e);
                    }
                }
            }
            PushAction::Update {
                local,
                variable_changes,
                ..
            } => {
                // Create any new variables first
                let resolved = match resolve_variables(
                    &local,
                    &variable_changes,
                    &mut vars_by_code_name,
                    args.debug,
                ) {
                    Ok(r) => r,
                    Err(e) => {
                        println!(
                            "{} Failed to resolve variables for {}: {}",
                            "✗".red(),
                            local.name,
                            e
                        );
                        continue;
                    }
                };

                match update_endpoint(&local, &resolved, args.debug) {
                    Ok(updated) => {
                        println!("{} Updated: {}", "✓".green(), local.name.bold());
                        if let Some(ui_url) = &updated.ui_url {
                            println!("  {ui_url}");
                        }
                        success_count += 1;
                    }
                    Err(e) => {
                        println!("{} Failed to update {}: {}", "✗".red(), local.name, e);
                    }
                }
            }
            PushAction::Skip { .. } => {}
        }
    }

    println!();
    println!(
        "{} endpoint{} synced.",
        success_count,
        if success_count == 1 { "" } else { "s" }
    );

    Ok(())
}

/// Collect YAML files from the given paths
fn collect_yaml_files(paths: &[String]) -> Result<Vec<(String, String)>> {
    let mut files = Vec::new();

    for path_str in paths {
        let path = Path::new(path_str);

        if path.is_dir() {
            // Collect all .yaml and .yml files from directory
            for entry in walkdir::WalkDir::new(path)
                .max_depth(1)
                .into_iter()
                .filter_map(|e| e.ok())
            {
                let entry_path = entry.path();
                if entry_path.is_file() {
                    if let Some(ext) = entry_path.extension() {
                        if ext == "yaml" || ext == "yml" {
                            let content = fs::read_to_string(entry_path).with_context(|| {
                                format!("Failed to read {}", entry_path.display())
                            })?;
                            files.push((entry_path.display().to_string(), content));
                        }
                    }
                }
            }
        } else if path.is_file() {
            let content =
                fs::read_to_string(path).with_context(|| format!("Failed to read {path_str}"))?;
            files.push((path_str.clone(), content));
        } else {
            // Try glob pattern
            let glob_pattern = globset::Glob::new(path_str)
                .with_context(|| format!("Invalid path pattern: {path_str}"))?
                .compile_matcher();

            let current_dir = std::env::current_dir()?;
            for entry in walkdir::WalkDir::new(&current_dir)
                .max_depth(3)
                .into_iter()
                .filter_map(|e| e.ok())
            {
                let entry_path = entry.path();
                if entry_path.is_file() {
                    let relative = entry_path.strip_prefix(&current_dir).unwrap_or(entry_path);
                    if glob_pattern.is_match(relative) {
                        let content = fs::read_to_string(entry_path)
                            .with_context(|| format!("Failed to read {}", entry_path.display()))?;
                        files.push((entry_path.display().to_string(), content));
                    }
                }
            }
        }
    }

    Ok(files)
}

/// Parse a YAML file into an EndpointYaml
fn parse_yaml_file(path: &str, content: &str) -> Result<EndpointYaml> {
    serde_yaml::from_str(content).with_context(|| format!("Failed to parse YAML in {path}"))
}

/// Print a preview of the query
fn print_query_preview(endpoint: &EndpointYaml) {
    if let Some(query) = &endpoint.query {
        let preview: String = query
            .lines()
            .take(3)
            .collect::<Vec<_>>()
            .join(" ")
            .chars()
            .take(60)
            .collect();
        println!("    Query: {}...", preview.dimmed());
    } else if let Some(query_def) = &endpoint.query_definition {
        if let Some(kind) = query_def.get("kind") {
            println!("    Query type: {kind}");
        }
    }
}

/// Print variable changes in the diff display
fn print_variable_changes(changes: &[VariableChange]) {
    if changes.is_empty() {
        return;
    }

    println!("    Variables:");
    for change in changes {
        match change {
            VariableChange::Create(var) => {
                println!(
                    "      {} {} ({})",
                    "+".green(),
                    var.name.green(),
                    var.var_type.dimmed()
                );
            }
            VariableChange::Update {
                code_name,
                from_type,
                to_type,
            } => {
                println!(
                    "      {} {} ({} → {})",
                    "~".yellow(),
                    code_name.yellow(),
                    from_type.dimmed(),
                    to_type.dimmed()
                );
            }
            VariableChange::Remove(code_name) => {
                println!("      {} {}", "-".red(), code_name.red());
            }
        }
    }
}

/// Compute variable changes between local YAML and remote state
fn compute_variable_changes(
    local: &EndpointYaml,
    remote_vars: &[String],
    existing_vars: &HashMap<String, InsightVariable>,
) -> Vec<VariableChange> {
    let mut changes = Vec::new();

    let local_vars = local.variables.as_ref();

    // Variables being added
    if let Some(vars) = local_vars {
        for var in vars {
            if !remote_vars.contains(&var.name) {
                // Variable will be added to this endpoint (may need to be created globally first)
                changes.push(VariableChange::Create(var.clone()));
            } else if let Some(existing) = existing_vars.get(&var.name) {
                // Variable exists - check for type changes
                if existing.var_type != var.var_type {
                    changes.push(VariableChange::Update {
                        code_name: var.name.clone(),
                        from_type: existing.var_type.clone(),
                        to_type: var.var_type.clone(),
                    });
                }
            }
        }
    }

    // Variables being removed
    let local_var_names: Vec<String> = local_vars
        .map(|v| v.iter().map(|var| var.name.clone()).collect())
        .unwrap_or_default();

    for remote_var in remote_vars {
        if !local_var_names.contains(remote_var) {
            changes.push(VariableChange::Remove(remote_var.clone()));
        }
    }

    changes
}

/// Resolve variables: look up existing ones, create missing ones
fn resolve_variables(
    endpoint: &EndpointYaml,
    variable_changes: &[VariableChange],
    vars_by_code_name: &mut HashMap<String, InsightVariable>,
    debug: bool,
) -> Result<ResolvedVariables> {
    let mut resolved = ResolvedVariables::new();

    let local_vars = match &endpoint.variables {
        Some(v) => v,
        None => return Ok(resolved),
    };

    for local_var in local_vars {
        // Check if we already have this variable
        if let Some(existing) = vars_by_code_name.get(&local_var.name) {
            resolved.insert(
                local_var.name.clone(),
                (existing.id.clone(), existing.clone()),
            );
        } else {
            // Need to create the variable
            let is_being_created = variable_changes
                .iter()
                .any(|c| matches!(c, VariableChange::Create(v) if v.name == local_var.name));

            if is_being_created {
                println!("  {} Creating variable '{}'...", "→".cyan(), local_var.name);

                let request = CreateInsightVariableRequest {
                    name: local_var.name.clone(), // Use code_name as display name
                    code_name: local_var.name.clone(),
                    var_type: local_var.var_type.clone(),
                    default_value: local_var.default.clone(),
                };

                let created = create_insight_variable(&request, debug)?;

                // Add to our cache
                vars_by_code_name.insert(created.code_name.clone(), created.clone());
                resolved.insert(local_var.name.clone(), (created.id.clone(), created));
            }
        }
    }

    Ok(resolved)
}

/// Create an endpoint via API
fn create_endpoint(
    endpoint: &EndpointYaml,
    resolved: &ResolvedVariables,
    debug: bool,
) -> Result<EndpointResponse> {
    let client = &context().client;
    let resolved_opt = if resolved.is_empty() {
        None
    } else {
        Some(resolved)
    };
    let request_body = endpoint.to_api_request(resolved_opt);

    if debug {
        eprintln!("  {} POST endpoints/", "DEBUG".cyan().bold());
        if let Ok(json) = serde_json::to_string_pretty(&request_body) {
            eprintln!("  Request body:\n{}", json.dimmed());
        }
    }

    let result = client.send_post(client.env_url("endpoints/")?, |req| req.json(&request_body));

    match result {
        Ok(response) => response.json().context("Failed to parse create response"),
        Err(e) => {
            if debug {
                eprintln!("  {} {}", "Error:".red(), e);
            }
            Err(e).context("Failed to create endpoint")
        }
    }
}

/// Update an endpoint via API
fn update_endpoint(
    endpoint: &EndpointYaml,
    resolved: &ResolvedVariables,
    debug: bool,
) -> Result<EndpointResponse> {
    let client = &context().client;
    let resolved_opt = if resolved.is_empty() {
        None
    } else {
        Some(resolved)
    };
    let request_body = endpoint.to_api_request(resolved_opt);
    let url = client.env_url(&format!("endpoints/{}/", endpoint.name))?;

    if debug {
        eprintln!(
            "  {} PATCH endpoints/{}/",
            "DEBUG".cyan().bold(),
            endpoint.name
        );
        if let Ok(json) = serde_json::to_string_pretty(&request_body) {
            eprintln!("  Request body:\n{}", json.dimmed());
        }
    }

    let result = client.send_request(reqwest::Method::PATCH, url, |req| req.json(&request_body));

    match result {
        Ok(response) => response.json().context("Failed to parse update response"),
        Err(e) => {
            if debug {
                eprintln!("  {} {}", "Error:".red(), e);
            }
            Err(e).context("Failed to update endpoint")
        }
    }
}
