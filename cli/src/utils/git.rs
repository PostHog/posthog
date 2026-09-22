use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use url::Url;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GitInfo {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub remote_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repo_name: Option<String>,
    pub branch: String,
    pub commit_id: String,
}

struct GitRepositoryPaths {
    git_dir: PathBuf,
    common_dir: PathBuf,
    worktree_dir: PathBuf,
}

pub fn get_git_info(dir: Option<PathBuf>) -> Result<Option<GitInfo>> {
    if let Some(info) = get_git_info_from_env(get_env_variable) {
        return Ok(Some(info));
    }

    let repository_paths = match find_git_repository_paths(dir) {
        Some(paths) => paths,
        None => return Ok(None),
    };

    let remote_url = get_remote_url_from_paths(&repository_paths);
    let repo_name = get_repo_name_from_paths(&repository_paths);
    let branch =
        get_branch_name(&repository_paths.git_dir).context("Failed to determine current branch")?;
    let commit =
        get_commit_sha(&repository_paths, &branch).context("Failed to determine commit sha")?;

    Ok(Some(GitInfo {
        remote_url,
        repo_name,
        branch,
        commit_id: commit,
    }))
}

#[doc(hidden)]
pub fn get_git_info_from_env(get_env: impl Fn(&str) -> Option<String>) -> Option<GitInfo> {
    if let Some(info) = get_git_info_from_github(&get_env) {
        return Some(info);
    }

    get_git_info_from_vercel(&get_env)
}

fn get_git_info_from_github(get_env: &impl Fn(&str) -> Option<String>) -> Option<GitInfo> {
    get_env("GITHUB_ACTIONS")?;

    let branch = get_env("GITHUB_REF_NAME")?;
    let commit_id = get_env("GITHUB_SHA")?;
    let repository = get_env("GITHUB_REPOSITORY")?;
    let server_url = get_env("GITHUB_SERVER_URL")?;

    let repo_name = repository.split('/').next_back().map(|s| s.to_string());
    let remote_url = Some(format!("{server_url}/{repository}.git"));

    Some(GitInfo {
        remote_url,
        repo_name,
        branch,
        commit_id,
    })
}

fn get_git_info_from_vercel(get_env: &impl Fn(&str) -> Option<String>) -> Option<GitInfo> {
    get_env("VERCEL")?;

    let branch = get_env("VERCEL_GIT_COMMIT_REF")?;
    let commit_id = get_env("VERCEL_GIT_COMMIT_SHA")?;
    let repo_slug = get_env("VERCEL_GIT_REPO_SLUG")?;

    let remote_url = build_vercel_remote_url(&repo_slug, get_env);

    Some(GitInfo {
        remote_url,
        repo_name: Some(repo_slug),
        branch,
        commit_id,
    })
}

fn build_vercel_remote_url(
    repo_slug: &str,
    get_env: &impl Fn(&str) -> Option<String>,
) -> Option<String> {
    let provider = get_env("VERCEL_GIT_PROVIDER")?;
    let owner = get_env("VERCEL_GIT_REPO_OWNER")?;

    let base_url = match provider.as_str() {
        "github" => "https://github.com",
        "gitlab" => "https://gitlab.com",
        "bitbucket" => "https://bitbucket.org",
        _ => return None,
    };

    Some(format!("{base_url}/{owner}/{repo_slug}.git"))
}

fn find_git_repository_paths(dir: Option<PathBuf>) -> Option<GitRepositoryPaths> {
    let mut current_dir = dir.unwrap_or(std::env::current_dir().ok()?);

    loop {
        let git_path = current_dir.join(".git");
        if git_path.is_dir() {
            let git_dir = normalize_existing_path(git_path);
            return Some(GitRepositoryPaths {
                common_dir: git_dir.clone(),
                git_dir,
                worktree_dir: current_dir,
            });
        }

        if git_path.is_file() {
            let git_dir = parse_git_dir_file(&git_path)?;
            let common_dir = get_common_dir(&git_dir);
            return Some(GitRepositoryPaths {
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
    let mut paths = vec![git_dir.join("config.worktree")];

    if common_dir != git_dir {
        paths.push(common_dir.join("config"));
    }

    paths.push(git_dir.join("config"));
    paths
}

pub fn get_remote_url(git_dir: &Path) -> Option<String> {
    get_remote_url_from_paths(&GitRepositoryPaths {
        git_dir: git_dir.to_path_buf(),
        common_dir: git_dir.to_path_buf(),
        worktree_dir: git_dir.parent().unwrap_or(git_dir).to_path_buf(),
    })
}

fn get_remote_url_from_paths(paths: &GitRepositoryPaths) -> Option<String> {
    // Try grab it from the git config
    for config_path in config_paths(&paths.git_dir, &paths.common_dir) {
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
                let sanitized = strip_credentials(url)?;
                let normalized = if sanitized.ends_with(".git") {
                    sanitized
                } else {
                    format!("{sanitized}.git")
                };
                return Some(normalized);
            }
        }
    }

    None
}

/// Drops every part of a URL that can carry a credential before it is stored anywhere: the
/// userinfo component (`user[:pass]@`), the query, and the fragment. CI checkouts commonly
/// write a remote URL with an embedded credential (e.g. `actions/checkout`'s
/// `https://x-access-token:<token>@github.com/owner/repo.git`), and that credential must never
/// reach release metadata.
///
/// Returns `None` for a URL whose credential sits where no parser can identify it, rather than
/// store it. That covers a URL holding an `@` that does not parse, because userinfo must
/// percent-encode `/`, `?` and `#`, and a URL holding an `@` in its path.
fn strip_credentials(url: &str) -> Option<String> {
    // A query or a fragment can hold a token (`?token=`, `#access_token=`) and a git remote
    // needs neither, so both go before anything else looks at the URL.
    let trimmed = match url.find(['?', '#']) {
        Some(index) => &url[..index],
        None => url,
    };

    // Dropping the delimiter can drop an `@` with it, which leaves nothing to tell a malformed
    // credential (`https://user:token?x@host/owner/repo.git`) from a query that holds an `@`.
    // What remains can be the credential itself, so the input is refused rather than stored.
    if url.contains('@') && !trimmed.contains('@') {
        return None;
    }
    let url = trimmed;

    // SCP-like SSH remotes (`git@host:owner/repo.git`) have no `://` authority to parse, and
    // the leading `git` is a fixed SSH username rather than a stored secret. A second `@` sits
    // in the path, where the rule below applies.
    if !url.contains("://") {
        let path = url.split_once(':').map_or("", |(_, path)| path);
        return if path.contains('@') {
            None
        } else {
            Some(url.to_string())
        };
    }

    let Ok(mut parsed) = Url::parse(url) else {
        return if url.contains('@') {
            None
        } else {
            Some(url.to_string())
        };
    };

    // An `@` in the path is a credential written into the wrong position, most often
    // `https://host/${TOKEN}@host/owner/repo.git` from a CI script that meant to write
    // `https://${TOKEN}@host/owner/repo.git`. Nothing tells that token from a path segment.
    if parsed.path().contains('@') {
        return None;
    }

    // Return the input untouched when it holds no credential, so the parser never reshapes a
    // URL that this function does not need to change.
    if parsed.username().is_empty() && parsed.password().is_none() {
        return Some(url.to_string());
    }

    // Both setters fail only for a URL that cannot have an authority, such as `mailto:`. A URL
    // that parsed with userinfo always has one.
    parsed.set_username("").ok()?;
    parsed.set_password(None).ok()?;
    Some(parsed.to_string())
}

pub fn get_repo_name(git_dir: &Path) -> Option<String> {
    get_repo_name_from_paths(&GitRepositoryPaths {
        git_dir: git_dir.to_path_buf(),
        common_dir: git_dir.to_path_buf(),
        worktree_dir: git_dir.parent().unwrap_or(git_dir).to_path_buf(),
    })
}

fn get_repo_name_from_paths(paths: &GitRepositoryPaths) -> Option<String> {
    // Try grab it from the configured remote, otherwise just use the directory name
    'configs: for config_path in config_paths(&paths.git_dir, &paths.common_dir) {
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
                // A remote with no path puts the authority in the last segment, so the name
                // is taken from the sanitized URL. Fall back to the directory name when the
                // URL cannot be sanitized, rather than name the repository after a credential.
                let Some(sanitized) = strip_credentials(url) else {
                    break 'configs;
                };
                if let Some(repo_name) = sanitized.split('/').next_back() {
                    let clean_name = repo_name.trim_end_matches(".git");
                    if !clean_name.is_empty() {
                        return Some(clean_name.to_string());
                    }
                }
                break 'configs;
            }
        }
    }

    if let Some(name) = paths.worktree_dir.file_name() {
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

fn get_commit_sha(paths: &GitRepositoryPaths, branch: &str) -> Result<String> {
    let git_dir = &paths.git_dir;

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

    // Try to read the commit from the branch reference (loose ref)
    for ref_path in branch_ref_paths(paths, branch) {
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

    // Fall back to packed-refs — Git packs loose refs into this file during
    // garbage collection or clone, which is common on Windows and in CI.
    if let Some(commit_id) = get_packed_ref(paths, branch) {
        return Ok(commit_id);
    }

    anyhow::bail!("Could not determine commit ID")
}

fn branch_ref_paths(paths: &GitRepositoryPaths, branch: &str) -> Vec<PathBuf> {
    let mut ref_paths = vec![paths.git_dir.join("refs/heads").join(branch)];

    if paths.common_dir != paths.git_dir {
        ref_paths.push(paths.common_dir.join("refs/heads").join(branch));
    }

    ref_paths
}

fn get_packed_ref(paths: &GitRepositoryPaths, branch: &str) -> Option<String> {
    let ref_name = format!("refs/heads/{branch}");
    let mut packed_ref_paths = vec![paths.git_dir.join("packed-refs")];

    if paths.common_dir != paths.git_dir {
        packed_ref_paths.push(paths.common_dir.join("packed-refs"));
    }

    for path in packed_ref_paths {
        let Ok(content) = fs::read_to_string(path) else {
            continue;
        };

        if let Some(commit_id) = parse_packed_refs(&content, &ref_name) {
            return Some(commit_id);
        }
    }

    None
}

fn parse_packed_refs(content: &str, ref_name: &str) -> Option<String> {
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

    None
}

fn get_env_variable(name: &str) -> Option<String> {
    let env_variable = std::env::var(name).ok()?.trim().to_string();
    match env_variable.as_ref() {
        "" => None,
        _ => Some(env_variable),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strip_credentials_handles_remote_url_shapes() {
        // `None` means the URL is refused, so no credential can reach release metadata.
        let cases = [
            (
                "github actions checkout token",
                "https://x-access-token:ghs_abc123def456@github.com/owner/repo.git",
                Some("https://github.com/owner/repo.git"),
            ),
            (
                "generic user and password",
                "https://user:secret@host/owner/repo.git",
                Some("https://host/owner/repo.git"),
            ),
            (
                "token as the username",
                "https://token@github.com/owner/repo.git",
                Some("https://github.com/owner/repo.git"),
            ),
            (
                "host and port are kept",
                "https://user:secret@git.example.com:8443/owner/repo.git",
                Some("https://git.example.com:8443/owner/repo.git"),
            ),
            (
                "the path survives the rewrite",
                "https://x-access-token:ghs_abc@github.com/owner/repo.git",
                Some("https://github.com/owner/repo.git"),
            ),
            (
                "a query is dropped, because it can hold a token",
                "https://github.com/owner/repo.git?token=ghs_abc",
                Some("https://github.com/owner/repo.git"),
            ),
            (
                "a fragment is dropped, because it can hold a token",
                "https://github.com/owner/repo.git#access_token=ghs_abc",
                Some("https://github.com/owner/repo.git"),
            ),
            (
                "a query is dropped from an scp-like ssh remote too",
                "git@github.com:owner/repo.git?token=ghs_abc",
                Some("git@github.com:owner/repo.git"),
            ),
            (
                "url without a credential is unchanged",
                "https://github.com/owner/repo.git",
                Some("https://github.com/owner/repo.git"),
            ),
            (
                "scp-like ssh remote is unchanged, because `git` is a fixed ssh username",
                "git@github.com:owner/repo.git",
                Some("git@github.com:owner/repo.git"),
            ),
            (
                "a token in the path is refused, because nothing tells it from a path segment",
                "https://github.com/ghs_abc123def456@github.com/owner/repo.git",
                None,
            ),
            (
                "any other `@` in the path is refused for the same reason",
                "https://github.com/owner/repo@v2.git",
                None,
            ),
            (
                "a second `@` in an scp-like path is refused too",
                "git@github.com:ghs_abc123@owner/repo.git",
                None,
            ),
            (
                "a `?` before the `@` is refused, because dropping the query drops the `@`",
                "https://user:ghp_abc123?x@github.com/owner/repo.git",
                None,
            ),
            (
                "a `#` before the `@` is refused for the same reason",
                "https://user:ghp_abc123#x@github.com/owner/repo.git",
                None,
            ),
            (
                "the truncated prefix is refused even when it parses as a host on its own",
                "https://ghp_abc123?suffix@github.com/owner/repo.git",
                None,
            ),
            (
                "ssh url with a credential",
                "ssh://user:secret@host/owner/repo.git",
                Some("ssh://host/owner/repo.git"),
            ),
            (
                "git protocol url is unchanged",
                "git://github.com/owner/repo.git",
                Some("git://github.com/owner/repo.git"),
            ),
            (
                "unencoded `/` in a password hides the credential, so the url is refused",
                "https://user:ab/cd+ef=@github.com/owner/repo.git",
                None,
            ),
        ];

        for (name, url, expected) in cases {
            assert_eq!(strip_credentials(url).as_deref(), expected, "case: {name}");
        }
    }

    fn write_config(url: &str) -> (tempfile::TempDir, GitRepositoryPaths) {
        let dir = tempfile::tempdir().unwrap();
        let git_dir = dir.path().join(".git");
        fs::create_dir_all(&git_dir).unwrap();
        fs::write(
            git_dir.join("config"),
            format!("[remote \"origin\"]\n\turl = {url}\n"),
        )
        .unwrap();
        let paths = GitRepositoryPaths {
            git_dir: git_dir.clone(),
            common_dir: git_dir,
            worktree_dir: dir.path().to_path_buf(),
        };
        (dir, paths)
    }

    #[test]
    fn get_remote_url_from_paths_strips_credential_from_config() {
        let (_dir, paths) =
            write_config("https://x-access-token:ghs_abc123@github.com/owner/repo.git");

        assert_eq!(
            get_remote_url_from_paths(&paths),
            Some("https://github.com/owner/repo.git".to_string())
        );

        // The `.git` suffix is normalized after the query goes, so the suffix check sees the
        // real end of the URL.
        let (_dir, paths) =
            write_config("https://x-access-token:ghs_abc123@github.com/owner/repo.git?ref=main");

        assert_eq!(
            get_remote_url_from_paths(&paths),
            Some("https://github.com/owner/repo.git".to_string())
        );
    }

    #[test]
    fn get_repo_name_from_paths_never_returns_a_credential() {
        let (_dir, paths) = write_config("https://user:ghp_abc123@github.com/owner/repo.git");
        assert_eq!(get_repo_name_from_paths(&paths), Some("repo".to_string()));

        // A truncated prefix parses as a host, which would otherwise name the repository
        // after the credential.
        let (dir, paths) = write_config("https://ghp_abc123?suffix@github.com/owner/repo.git");
        let name = get_repo_name_from_paths(&paths).unwrap();
        assert!(
            !name.contains("ghp_abc123"),
            "credential leaked into repo name: {name}"
        );
        assert_eq!(name, dir.path().file_name().unwrap().to_string_lossy());

        // A remote with no path would otherwise name the repository after the authority.
        let (dir, paths) = write_config("https://user:ghp_abc123@github.com");
        let name = get_repo_name_from_paths(&paths).unwrap();
        assert!(
            !name.contains("ghp_abc123"),
            "credential leaked into repo name: {name}"
        );
        assert_eq!(name, dir.path().file_name().unwrap().to_string_lossy());
    }
}
