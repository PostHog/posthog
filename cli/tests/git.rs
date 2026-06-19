use posthog_cli::utils::git::{get_git_info_from_env, get_remote_url, get_repo_name};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use uuid::Uuid;

fn env_from<const N: usize>(values: [(&str, &str); N]) -> impl Fn(&str) -> Option<String> {
    let env = values
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect::<HashMap<_, _>>();
    move |key| env.get(key).cloned()
}

fn make_git_dir_with_config(config_content: &str) -> PathBuf {
    let temp_root = std::env::temp_dir().join(format!("posthog_cli_git_test_{}", Uuid::now_v7()));
    let git_dir = temp_root.join(".git");
    fs::create_dir_all(&git_dir).expect("failed to create .git directory");
    let config_path = git_dir.join("config");
    fs::write(&config_path, config_content).expect("failed to write config");
    git_dir
}

#[test]
fn test_get_repo_infos_https_with_dot_git() {
    let cfg = r#"
[core]
    repositoryformatversion = 0
[remote "origin"]
    url = https://github.com/PostHog/posthog.git
    fetch = +refs/heads/*:refs/remotes/origin/*
"#;
    let git_dir = make_git_dir_with_config(cfg);
    assert_eq!(
        get_remote_url(&git_dir).as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );
    assert_eq!(get_repo_name(&git_dir).as_deref(), Some("posthog"));
    let _ = fs::remove_dir_all(git_dir.parent().unwrap());
}

#[test]
fn test_get_repo_infos_https_without_dot_git() {
    let cfg = r#"
[core]
    repositoryformatversion = 0
[remote "origin"]
    url = https://github.com/PostHog/posthog
    fetch = +refs/heads/*:refs/remotes/origin/*
"#;
    let git_dir = make_git_dir_with_config(cfg);
    assert_eq!(
        get_remote_url(&git_dir).as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );
    assert_eq!(get_repo_name(&git_dir).as_deref(), Some("posthog"));
    let _ = fs::remove_dir_all(git_dir.parent().unwrap());
}

#[test]
fn test_get_repo_infos_ssh_with_dot_git() {
    let cfg = r#"
[core]
    repositoryformatversion = 0
[remote "origin"]
    url = git@github.com:PostHog/posthog.git
    fetch = +refs/heads/*:refs/remotes/origin/*
"#;
    let git_dir = make_git_dir_with_config(cfg);
    assert_eq!(
        get_remote_url(&git_dir).as_deref(),
        Some("git@github.com:PostHog/posthog.git")
    );
    assert_eq!(get_repo_name(&git_dir).as_deref(), Some("posthog"));
    let _ = fs::remove_dir_all(git_dir.parent().unwrap());
}

#[test]
fn test_get_repo_infos_ssh_without_dot_git() {
    let cfg = r#"
[core]
    repositoryformatversion = 0
[remote "origin"]
    url = git@github.com:PostHog/posthog
    fetch = +refs/heads/*:refs/remotes/origin/*
"#;
    let git_dir = make_git_dir_with_config(cfg);
    assert_eq!(
        get_remote_url(&git_dir).as_deref(),
        Some("git@github.com:PostHog/posthog.git")
    );
    assert_eq!(get_repo_name(&git_dir).as_deref(), Some("posthog"));
    let _ = fs::remove_dir_all(git_dir.parent().unwrap());
}

#[test]
fn test_get_git_info_from_vercel_env() {
    let info = get_git_info_from_env(env_from([
        ("VERCEL", "1"),
        ("VERCEL_GIT_PROVIDER", "github"),
        ("VERCEL_GIT_REPO_OWNER", "PostHog"),
        ("VERCEL_GIT_REPO_SLUG", "posthog"),
        ("VERCEL_GIT_COMMIT_REF", "main"),
        ("VERCEL_GIT_COMMIT_SHA", "abc123def456"),
    ]))
    .expect("should return info");

    assert_eq!(info.branch, "main");
    assert_eq!(info.commit_id, "abc123def456");
    assert_eq!(info.repo_name.as_deref(), Some("posthog"));
    assert_eq!(
        info.remote_url.as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );
}

#[test]
fn test_get_git_info_from_github_env() {
    let info = get_git_info_from_env(env_from([
        ("GITHUB_ACTIONS", "true"),
        ("GITHUB_SHA", "abc123def456"),
        ("GITHUB_REF_NAME", "main"),
        ("GITHUB_REPOSITORY", "PostHog/posthog"),
        ("GITHUB_SERVER_URL", "https://github.com"),
    ]))
    .expect("should return info");

    assert_eq!(info.branch, "main");
    assert_eq!(info.commit_id, "abc123def456");
    assert_eq!(info.repo_name.as_deref(), Some("posthog"));
    assert_eq!(
        info.remote_url.as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );
}

#[test]
fn test_get_git_info_prefers_github_env_over_vercel_env() {
    let info = get_git_info_from_env(env_from([
        ("GITHUB_ACTIONS", "true"),
        ("GITHUB_SHA", "github-sha"),
        ("GITHUB_REF_NAME", "github-branch"),
        ("GITHUB_REPOSITORY", "PostHog/posthog"),
        ("GITHUB_SERVER_URL", "https://github.com"),
        ("VERCEL", "1"),
        ("VERCEL_GIT_PROVIDER", "github"),
        ("VERCEL_GIT_REPO_OWNER", "PostHog"),
        ("VERCEL_GIT_REPO_SLUG", "posthog"),
        ("VERCEL_GIT_COMMIT_REF", "vercel-branch"),
        ("VERCEL_GIT_COMMIT_SHA", "vercel-sha"),
    ]))
    .expect("should return info");

    assert_eq!(info.branch, "github-branch");
    assert_eq!(info.commit_id, "github-sha");
}
