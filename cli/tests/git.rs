use posthog_cli::utils::git::{get_remote_url, get_repo_name};
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
