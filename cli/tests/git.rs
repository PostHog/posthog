use posthog_cli::utils::git::{get_git_info, get_git_info_from_env, get_remote_url, get_repo_name};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::sync::{Mutex, MutexGuard};
use uuid::Uuid;

fn env_from<const N: usize>(values: [(&str, &str); N]) -> impl Fn(&str) -> Option<String> {
    let env = values
        .into_iter()
        .map(|(key, value)| (key.to_string(), value.to_string()))
        .collect::<HashMap<_, _>>();
    move |key| env.get(key).cloned()
}

static ENV_LOCK: Mutex<()> = Mutex::new(());

fn lock_env() -> MutexGuard<'static, ()> {
    ENV_LOCK
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
}

const GIT_INFO_ENV_VARS: &[&str] = &[
    "GITHUB_ACTIONS",
    "GITHUB_SHA",
    "GITHUB_REF_NAME",
    "GITHUB_REPOSITORY",
    "GITHUB_SERVER_URL",
    "VERCEL",
    "VERCEL_GIT_PROVIDER",
    "VERCEL_GIT_REPO_OWNER",
    "VERCEL_GIT_REPO_SLUG",
    "VERCEL_GIT_COMMIT_REF",
    "VERCEL_GIT_COMMIT_SHA",
];

fn make_git_dir_with_config(config_content: &str) -> PathBuf {
    let temp_root = std::env::temp_dir().join(format!("posthog_cli_git_test_{}", Uuid::now_v7()));
    let git_dir = temp_root.join(".git");
    fs::create_dir_all(&git_dir).expect("failed to create .git directory");
    let config_path = git_dir.join("config");
    fs::write(&config_path, config_content).expect("failed to write config");
    git_dir
}

fn remove_env_vars(names: &[&str]) -> Vec<(String, Option<String>)> {
    names
        .iter()
        .map(|name| {
            let value = std::env::var(name).ok();
            std::env::remove_var(name);
            ((*name).to_string(), value)
        })
        .collect()
}

struct EnvVarGuard(Vec<(String, Option<String>)>);

impl EnvVarGuard {
    fn clear(names: &[&str]) -> Self {
        Self(remove_env_vars(names))
    }
}

impl Drop for EnvVarGuard {
    fn drop(&mut self) {
        for (name, value) in self.0.drain(..) {
            match value {
                Some(value) => std::env::set_var(name, value),
                None => std::env::remove_var(name),
            }
        }
    }
}

fn write_repo_config(git_dir: &std::path::Path) {
    fs::write(
        git_dir.join("config"),
        r#"
[core]
    repositoryformatversion = 0
[remote "origin"]
    url = https://github.com/PostHog/posthog.git
    fetch = +refs/heads/*:refs/remotes/origin/*
"#,
    )
    .expect("failed to write config");
}

fn write_head(git_dir: &std::path::Path, branch: &str) {
    fs::write(git_dir.join("HEAD"), format!("ref: refs/heads/{branch}\n"))
        .expect("failed to write HEAD");
}

fn write_loose_ref(git_dir: &std::path::Path, branch: &str, commit_id: &str) {
    let branch_ref = git_dir.join("refs/heads").join(branch);
    fs::create_dir_all(branch_ref.parent().unwrap()).expect("failed to create refs directory");
    fs::write(branch_ref, format!("{commit_id}\n")).expect("failed to write branch ref");
}

fn write_packed_ref(git_dir: &std::path::Path, branch: &str, commit_id: &str) {
    fs::write(
        git_dir.join("packed-refs"),
        format!("# pack-refs with: peeled fully-peeled sorted\n{commit_id} refs/heads/{branch}\n"),
    )
    .expect("failed to write packed-refs");
}

fn assert_posthog_git_info(worktree_dir: PathBuf, branch: &str, commit_id: &str) {
    let info = get_git_info(Some(worktree_dir))
        .expect("should not error")
        .expect("should return info");

    assert_eq!(info.branch, branch);
    assert_eq!(info.commit_id, commit_id);
    assert_eq!(
        info.remote_url.as_deref(),
        Some("https://github.com/PostHog/posthog.git")
    );
    assert_eq!(info.repo_name.as_deref(), Some("posthog"));
}

#[test]
fn test_get_commit_sha_from_loose_ref() {
    let _env_lock = lock_env();
    let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);

    let temp_root =
        std::env::temp_dir().join(format!("posthog_cli_loose_ref_test_{}", Uuid::now_v7()));
    let git_dir = temp_root.join(".git");
    let branch = "main";
    let commit_id = "abc123def456abc123def456abc123def456abc1";

    fs::create_dir_all(&git_dir).expect("failed to create .git directory");
    write_head(&git_dir, branch);
    write_loose_ref(&git_dir, branch, commit_id);

    let info = get_git_info(Some(temp_root.clone()))
        .expect("get_git_info failed")
        .expect("expected Some(GitInfo)");

    assert_eq!(info.branch, branch);
    assert_eq!(info.commit_id, commit_id);
    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn test_get_commit_sha_loose_ref_takes_precedence_over_packed_refs() {
    let _env_lock = lock_env();
    let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);

    let temp_root = std::env::temp_dir().join(format!(
        "posthog_cli_ref_precedence_test_{}",
        Uuid::now_v7()
    ));
    let git_dir = temp_root.join(".git");
    let branch = "main";
    let loose_commit_id = "1111111111111111111111111111111111111111";
    let packed_commit_id = "cafebabecafebabecafebabecafebabecafebabe";

    fs::create_dir_all(&git_dir).expect("failed to create .git directory");
    write_head(&git_dir, branch);
    write_loose_ref(&git_dir, branch, loose_commit_id);
    write_packed_ref(&git_dir, branch, packed_commit_id);

    let info = get_git_info(Some(temp_root.clone()))
        .expect("get_git_info failed")
        .expect("expected Some(GitInfo)");

    assert_eq!(info.branch, branch);
    assert_eq!(info.commit_id, loose_commit_id);
    let _ = fs::remove_dir_all(temp_root);
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
fn test_get_git_info_from_regular_repo_packed_refs() {
    let _env_lock = lock_env();
    let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);

    let temp_root =
        std::env::temp_dir().join(format!("posthog_cli_regular_repo_test_{}", Uuid::now_v7()));
    let git_dir = temp_root.join(".git");
    let branch = "feature/packed";
    let commit_id = "0123456789abcdef0123456789abcdef01234567";

    fs::create_dir_all(&git_dir).expect("failed to create .git directory");
    write_head(&git_dir, branch);
    write_packed_ref(&git_dir, branch, commit_id);
    write_repo_config(&git_dir);

    assert_posthog_git_info(temp_root.clone(), branch, commit_id);

    let _ = fs::remove_dir_all(temp_root);
}

#[test]
fn test_get_git_info_from_worktree_git_file_cases() {
    let _env_lock = lock_env();
    let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);

    for (case_name, absolute_gitdir, commondir, use_packed_ref) in [
        (
            "relative loose ref in common dir",
            false,
            Some("../.."),
            false,
        ),
        (
            "absolute gitdir with packed ref in common dir",
            true,
            Some("../.."),
            true,
        ),
        (
            "no commondir uses worktree git dir packed ref",
            true,
            None,
            true,
        ),
    ] {
        let case_slug = case_name.replace(' ', "-");
        let temp_root = std::env::temp_dir().join(format!(
            "posthog_cli_worktree_test_{}_{}",
            case_slug,
            Uuid::now_v7()
        ));
        let worktree_dir = temp_root.join("worktree");
        let common_git_dir = temp_root.join("repo.git");
        let worktree_git_dir = common_git_dir.join("worktrees/worktree");
        let git_dir = if commondir.is_some() {
            worktree_git_dir.clone()
        } else {
            temp_root.join("single-worktree.git")
        };
        let branch = format!("feature/{case_slug}");
        let commit_id = "0123456789abcdef0123456789abcdef01234567";

        fs::create_dir_all(&worktree_dir).expect("failed to create worktree directory");
        fs::create_dir_all(&git_dir).expect("failed to create worktree git directory");
        fs::create_dir_all(&common_git_dir).expect("failed to create common git directory");

        let gitdir = if absolute_gitdir {
            git_dir.display().to_string()
        } else {
            "../repo.git/worktrees/worktree".to_string()
        };
        fs::write(worktree_dir.join(".git"), format!("gitdir: {gitdir}\n"))
            .expect("failed to write worktree .git file");
        if let Some(commondir) = commondir {
            fs::write(git_dir.join("commondir"), format!("{commondir}\n"))
                .expect("failed to write commondir");
        }
        write_head(&git_dir, &branch);

        let ref_git_dir = if commondir.is_some() {
            &common_git_dir
        } else {
            &git_dir
        };
        if use_packed_ref {
            write_packed_ref(ref_git_dir, &branch, commit_id);
        } else {
            write_loose_ref(ref_git_dir, &branch, commit_id);
        }
        write_repo_config(ref_git_dir);

        assert_posthog_git_info(worktree_dir, &branch, commit_id);

        let _ = fs::remove_dir_all(temp_root);
    }
}

#[test]
fn test_get_git_info_from_worktree_config_precedence() {
    let _env_lock = lock_env();
    let _env_guard = EnvVarGuard::clear(GIT_INFO_ENV_VARS);

    let temp_root = std::env::temp_dir().join(format!(
        "posthog_cli_worktree_config_test_{}",
        Uuid::now_v7()
    ));
    let worktree_dir = temp_root.join("worktree");
    let common_git_dir = temp_root.join("repo.git");
    let worktree_git_dir = common_git_dir.join("worktrees/worktree");
    let branch = "feature/config-worktree";
    let commit_id = "0123456789abcdef0123456789abcdef01234567";

    fs::create_dir_all(&worktree_dir).expect("failed to create worktree directory");
    fs::create_dir_all(&worktree_git_dir).expect("failed to create worktree git directory");
    fs::create_dir_all(&common_git_dir).expect("failed to create common git directory");
    fs::write(
        worktree_dir.join(".git"),
        format!("gitdir: {}\n", worktree_git_dir.display()),
    )
    .expect("failed to write worktree .git file");
    fs::write(worktree_git_dir.join("commondir"), "../..\n").expect("failed to write commondir");
    write_head(&worktree_git_dir, branch);
    write_loose_ref(&common_git_dir, branch, commit_id);
    write_repo_config(&common_git_dir);
    fs::write(
        worktree_git_dir.join("config.worktree"),
        r#"
[remote "origin"]
    url = https://github.com/PostHog/worktree-override.git
"#,
    )
    .expect("failed to write worktree config");

    let info = get_git_info(Some(worktree_dir))
        .expect("should not error")
        .expect("should return info");

    assert_eq!(info.branch, branch);
    assert_eq!(info.commit_id, commit_id);
    assert_eq!(
        info.remote_url.as_deref(),
        Some("https://github.com/PostHog/worktree-override.git")
    );
    assert_eq!(info.repo_name.as_deref(), Some("worktree-override"));

    let _ = fs::remove_dir_all(temp_root);
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
