use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GitInfo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub remote_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repo_name: Option<String>,
    pub branch: String,
    pub commit_id: String,
}

struct GitDirs {
    git_dir: PathBuf,
    common_dir: PathBuf,
    worktree_dir: PathBuf,
}

pub fn get_git_info(dir: Option<PathBuf>) -> Result<Option<GitInfo>> {
    if let Some(info) = get_git_info_from_github() {
        return Ok(Some(info));
    }

    if let Some(info) = get_git_info_from_vercel() {
        return Ok(Some(info));
    }

    let git_dirs = match find_git_dirs(dir) {
        Some(dirs) => dirs,
        None => return Ok(None),
    };

    let remote_url = get_remote_url_from_dirs(&git_dirs.git_dir, &git_dirs.common_dir);
    let repo_name = get_repo_name_from_dirs(
        &git_dirs.git_dir,
        &git_dirs.common_dir,
        Some(&git_dirs.worktree_dir),
    );
    let branch =
        get_branch_name(&git_dirs.git_dir).context("Failed to determine current branch")?;
    let commit = get_commit_sha(&git_dirs.git_dir, &git_dirs.common_dir, &branch)
        .context("Failed to determine commit sha")?;

    Ok(Some(GitInfo {
        remote_url,
        repo_name,
        branch,
        commit_id: commit,
    }))
}

fn get_git_info_from_github() -> Option<GitInfo> {
    get_env_variable("GITHUB_ACTIONS")?;

    let branch = get_env_variable("GITHUB_REF_NAME")?;
    let commit_id = get_env_variable("GITHUB_SHA")?;
    let repository = get_env_variable("GITHUB_REPOSITORY")?;
    let server_url = get_env_variable("GITHUB_SERVER_URL")?;

    let repo_name = repository.split('/').next_back().map(|s| s.to_string());
    let remote_url = Some(format!("{server_url}/{repository}.git"));

    Some(GitInfo {
        remote_url,
        repo_name,
        branch,
        commit_id,
    })
}

fn get_git_info_from_vercel() -> Option<GitInfo> {
    get_env_variable("VERCEL")?;

    let branch = get_env_variable("VERCEL_GIT_COMMIT_REF")?;
    let commit_id = get_env_variable("VERCEL_GIT_COMMIT_SHA")?;
    let repo_slug = get_env_variable("VERCEL_GIT_REPO_SLUG")?;

    let remote_url = build_vercel_remote_url(&repo_slug);

    Some(GitInfo {
        remote_url,
        repo_name: Some(repo_slug),
        branch,
        commit_id,
    })
}

fn build_vercel_remote_url(repo_slug: &String) -> Option<String> {
    let provider = get_env_variable("VERCEL_GIT_PROVIDER")?;
    let owner = get_env_variable("VERCEL_GIT_REPO_OWNER")?;

    let base_url = match provider.as_str() {
        "github" => "https://github.com",
        "gitlab" => "https://gitlab.com",
        "bitbucket" => "https://bitbucket.org",
        _ => return None,
    };

    Some(format!("{base_url}/{owner}/{repo_slug}.git"))
}

fn find_git_dirs(dir: Option<PathBuf>) -> Option<GitDirs> {
    let mut current_dir = dir.unwrap_or(std::env::current_dir().ok()?);

    loop {
        let git_path = current_dir.join(".git");
        if git_path.is_dir() {
            let git_dir = normalize_existing_path(git_path);
            return Some(GitDirs {
                common_dir: git_dir.clone(),
                git_dir,
                worktree_dir: current_dir,
            });
        }

        if git_path.is_file() {
            let git_dir = parse_git_dir_file(&git_path)?;
            let common_dir = get_common_dir(&git_dir);
            return Some(GitDirs {
                git_dir,
                common_dir,
                worktree_dir: current_dir,
            });
        }

        if !current_dir.pop() {
            return None;
        }
    }
}

fn parse_git_dir_file(git_path: &Path) -> Option<PathBuf> {
    let content = fs::read_to_string(git_path).ok()?;
    let git_dir = content.trim().strip_prefix("gitdir:")?.trim();
    let git_dir = PathBuf::from(git_dir);

    let git_dir = if git_dir.is_absolute() {
        git_dir
    } else {
        git_path.parent()?.join(git_dir)
    };

    Some(normalize_existing_path(git_dir))
}

fn get_common_dir(git_dir: &Path) -> PathBuf {
    let commondir_path = git_dir.join("commondir");
    let Ok(commondir) = fs::read_to_string(commondir_path) else {
        return git_dir.to_path_buf();
    };

    let commondir = PathBuf::from(commondir.trim());
    let common_dir = if commondir.is_absolute() {
        commondir
    } else {
        git_dir.join(commondir)
    };

    normalize_existing_path(common_dir)
}

fn normalize_existing_path(path: PathBuf) -> PathBuf {
    fs::canonicalize(&path).unwrap_or(path)
}

fn config_paths(git_dir: &Path, common_dir: &Path) -> Vec<PathBuf> {
    let mut paths = vec![git_dir.join("config"), git_dir.join("config.worktree")];

    if common_dir != git_dir {
        paths.push(common_dir.join("config"));
    }

    paths
}

pub fn get_remote_url(git_dir: &Path) -> Option<String> {
    get_remote_url_from_dirs(git_dir, git_dir)
}

fn get_remote_url_from_dirs(git_dir: &Path, common_dir: &Path) -> Option<String> {
    // Try grab it from the git config
    for config_path in config_paths(git_dir, common_dir) {
        if !config_path.exists() {
            continue;
        }

        let config_content = match fs::read_to_string(&config_path) {
            Ok(content) => content,
            Err(_) => continue,
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
    get_repo_name_from_dirs(git_dir, git_dir, git_dir.parent())
}

fn get_repo_name_from_dirs(
    git_dir: &Path,
    common_dir: &Path,
    worktree_dir: Option<&Path>,
) -> Option<String> {
    // Try grab it from the configured remote, otherwise just use the directory name
    for config_path in config_paths(git_dir, common_dir) {
        if !config_path.exists() {
            continue;
        }

        let config_content = match fs::read_to_string(&config_path) {
            Ok(content) => content,
            Err(_) => continue,
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

    if let Some(name) = worktree_dir.and_then(|dir| dir.file_name()) {
        return Some(name.to_string_lossy().to_string());
    }

    None
}

fn get_branch_name(git_dir: &Path) -> Result<String> {
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

fn get_commit_sha(git_dir: &Path, common_dir: &Path, branch: &str) -> Result<String> {
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
    for ref_path in branch_ref_paths(git_dir, common_dir, branch) {
        if !ref_path.exists() {
            continue;
        }

        let mut commit_id = String::new();
        fs::File::open(&ref_path)
            .with_context(|| format!("Failed to open branch reference at {ref_path:?}"))?
            .read_to_string(&mut commit_id)
            .context("Failed to read branch reference file")?;

        return Ok(commit_id.trim().to_string());
    }

    if let Some(commit_id) = get_packed_ref(git_dir, common_dir, branch) {
        return Ok(commit_id);
    }

    anyhow::bail!("Could not determine commit ID")
}

fn branch_ref_paths(git_dir: &Path, common_dir: &Path, branch: &str) -> Vec<PathBuf> {
    let mut paths = vec![git_dir.join("refs/heads").join(branch)];

    if common_dir != git_dir {
        paths.push(common_dir.join("refs/heads").join(branch));
    }

    paths
}

fn get_packed_ref(git_dir: &Path, common_dir: &Path, branch: &str) -> Option<String> {
    let ref_name = format!("refs/heads/{branch}");
    let mut paths = vec![git_dir.join("packed-refs")];

    if common_dir != git_dir {
        paths.push(common_dir.join("packed-refs"));
    }

    for path in paths {
        let Ok(content) = fs::read_to_string(path) else {
            continue;
        };

        for line in content.lines() {
            let line = line.trim();
            if line.is_empty() || line.starts_with('#') || line.starts_with('^') {
                continue;
            }

            let mut parts = line.split_whitespace();
            let Some(commit_id) = parts.next() else {
                continue;
            };
            let Some(packed_ref) = parts.next() else {
                continue;
            };

            if packed_ref == ref_name {
                return Some(commit_id.to_string());
            }
        }
    }

    None
}

fn get_env_variable(name: &str) -> Option<String> {
    let env_variable = std::env::var(name).ok()?.trim().to_string();
    match env_variable.as_ref() {
        "" => None,
        _ => Some(env_variable),
    }
}
