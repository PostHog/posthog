use posthog_cli::utils::git::{get_git_info, get_remote_url, get_repo_name};
use std::fs;
use std::path::PathBuf;
use uuid::Uuid;

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
    std::env::set_var("VERCEL", "1");
    std::env::set_var("VERCEL_GIT_PROVIDER", "github");
    std::env::set_var("VERCEL_GIT_REPO_OWNER", "PostHog");
    std::env::set_var("VERCEL_GIT_REPO_SLUG", "posthog");
    std::env::set_var("VERCEL_GIT_COMMIT_REF", "main");
    std::env::set_var("VERCEL_GIT_COMMIT_SHA", "abc123def456");

    let info = get_git_info(None)
        .expect("should not error")
        .expect("should return info");

    assert_eq!(info.branch, "main");
    assert_eq!(info.commit_id, "abc123def456");
    assert_eq!(info.repo_name.as_deref(), Some("posthog"));
    assert_eq!(
        info.remote_url.as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );

    std::env::remove_var("VERCEL");
    std::env::remove_var("VERCEL_GIT_PROVIDER");
    std::env::remove_var("VERCEL_GIT_REPO_OWNER");
    std::env::remove_var("VERCEL_GIT_REPO_SLUG");
    std::env::remove_var("VERCEL_GIT_COMMIT_REF");
    std::env::remove_var("VERCEL_GIT_COMMIT_SHA");
}

#[test]
fn test_get_git_info_from_github_env() {
    std::env::set_var("GITHUB_ACTIONS", "true");
    std::env::set_var("GITHUB_SHA", "abc123def456");
    std::env::set_var("GITHUB_REF_NAME", "main");
    std::env::set_var("GITHUB_REPOSITORY", "PostHog/posthog");
    std::env::set_var("GITHUB_SERVER_URL", "https://github.com");

    let info = get_git_info(None)
        .expect("should not error")
        .expect("should return info");

    assert_eq!(info.branch, "main");
    assert_eq!(info.commit_id, "abc123def456");
    assert_eq!(info.repo_name.as_deref(), Some("posthog"));
    assert_eq!(
        info.remote_url.as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );

    std::env::remove_var("GITHUB_ACTIONS");
    std::env::remove_var("GITHUB_SHA");
    std::env::remove_var("GITHUB_REF_NAME");
    std::env::remove_var("GITHUB_REPOSITORY");
    std::env::remove_var("GITHUB_SERVER_URL");
}
