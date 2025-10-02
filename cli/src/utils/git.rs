use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GitInfo {
    pub remote_url: Option<String>,
    pub repo_name: Option<String>,
    pub branch: String,
    pub commit_id: String,
}

pub fn get_git_info(dir: Option<PathBuf>) -> Result<Option<GitInfo>> {
    let git_dir = match find_git_dir(dir) {
        Some(dir) => dir,
        None => return Ok(None),
    };

    let remote_url = get_remote_url(&git_dir);
    let repo_name = get_repo_name(&git_dir);
    let branch = get_current_branch(&git_dir).context("Failed to determine current branch")?;
    let commit = get_head_commit(&git_dir, &branch).context("Failed to determine commit ID")?;

    Ok(Some(GitInfo {
        remote_url,
        repo_name,
        branch,
        commit_id: commit,
    }))
}

fn find_git_dir(dir: Option<PathBuf>) -> Option<PathBuf> {
    let mut current_dir = dir.unwrap_or(std::env::current_dir().ok()?);

    loop {
        let git_dir = current_dir.join(".git");
        if git_dir.is_dir() {
            return Some(git_dir);
        }

        if !current_dir.pop() {
            return None;
        }
    }
}

pub fn get_remote_url(git_dir: &Path) -> Option<String> {
    // Try grab it from the git config
    let config_path = git_dir.join("config");
    if config_path.exists() {
        let config_content = match fs::read_to_string(&config_path) {
            Ok(content) => content,
            Err(_) => return None,
        };

        for line in config_content.lines() {
            let line = line.trim();
            if line.starts_with("url = ") {
                let url = line.trim_start_matches("url = ").trim();
                let normalized = if url.ends_with(".git") {
                    url.to_string()
                } else {
                    format!("{url}.git")
                };
                return Some(normalized);
            }
        }
    }

    None
}

pub fn get_repo_name(git_dir: &Path) -> Option<String> {
    // Try grab it from the configured remote, otherwise just use the directory name
    let config_path = git_dir.join("config");
    if config_path.exists() {
        let config_content = match fs::read_to_string(&config_path) {
            Ok(content) => content,
            Err(_) => return None,
        };

        for line in config_content.lines() {
            let line = line.trim();
            if line.starts_with("url = ") {
                let url = line.trim_start_matches("url = ");
                if let Some(repo_name) = url.split('/').next_back() {
                    let clean_name = repo_name.trim_end_matches(".git");
                    return Some(clean_name.to_string());
                }
            }
        }
    }

    if let Some(parent) = git_dir.parent() {
        if let Some(name) = parent.file_name() {
            return Some(name.to_string_lossy().to_string());
        }
    }

    None
}

fn get_current_branch(git_dir: &Path) -> Result<String> {
    // First try to read from HEAD file
    let head_path = git_dir.join("HEAD");
    let mut head_content = String::new();
    fs::File::open(&head_path)
        .with_context(|| format!("Failed to open HEAD file at {head_path:?}"))?
        .read_to_string(&mut head_content)
        .context("Failed to read HEAD file")?;

    // Parse HEAD content
    if head_content.starts_with("ref: refs/heads/") {
        Ok(head_content
            .trim_start_matches("ref: refs/heads/")
            .trim()
            .to_string())
    } else if head_content.trim().len() == 40 || head_content.trim().len() == 64 {
        Ok("HEAD-detached".to_string())
    } else {
        anyhow::bail!("Unrecognized HEAD format")
    }
}

fn get_head_commit(git_dir: &Path, branch: &str) -> Result<String> {
    if branch == "HEAD-detached" {
        // For detached HEAD, read directly from HEAD
        let head_path = git_dir.join("HEAD");
        let mut head_content = String::new();
        fs::File::open(&head_path)
            .with_context(|| format!("Failed to open HEAD file at {head_path:?}"))?
            .read_to_string(&mut head_content)
            .context("Failed to read HEAD file")?;

        return Ok(head_content.trim().to_string());
    }

    // Try to read the commit from the branch reference
    let ref_path = git_dir.join("refs/heads").join(branch);
    if ref_path.exists() {
        let mut commit_id = String::new();
        fs::File::open(&ref_path)
            .with_context(|| format!("Failed to open branch reference at {ref_path:?}"))?
            .read_to_string(&mut commit_id)
            .context("Failed to read branch reference file")?;

        return Ok(commit_id.trim().to_string());
    }

    anyhow::bail!("Could not determine commit ID")
}
