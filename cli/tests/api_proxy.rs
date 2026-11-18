use std::fs;
use std::process::Command;

#[test]
fn api_forwards_all_arguments_to_the_script() {
    let dir = tempfile::tempdir().unwrap();
    let preloaded = dir.path().join("preloaded");
    let preload = dir.path().join("preload.cjs");
    fs::write(
        &preload,
        format!(
            "require('fs').writeFileSync({}, '')",
            serde_json::to_string(preloaded.to_str().unwrap()).unwrap()
        ),
    )
    .unwrap();
    let env_file = dir.path().join("node.env");
    fs::write(
        &env_file,
        format!("NODE_OPTIONS=--require={}\n", preload.display()),
    )
    .unwrap();
    let received = dir.path().join("received.json");
    let script = dir.path().join("api-cli.mjs");
    fs::write(
        &script,
        format!(
            "import {{ writeFileSync }} from 'node:fs'\nwriteFileSync({}, JSON.stringify(process.argv.slice(2)))\n",
            serde_json::to_string(received.to_str().unwrap()).unwrap()
        ),
    )
    .unwrap();

    let status = Command::new(env!("CARGO_BIN_EXE_posthog-cli"))
        .args(["api", "--env-file"])
        .arg(&env_file)
        .env("POSTHOG_API_CLI_PATH", &script)
        .env("POSTHOG_HOME", dir.path())
        .env_remove("NODE_OPTIONS")
        .status()
        .expect("run posthog-cli");

    assert!(status.success());
    let args: Vec<String> = serde_json::from_slice(&fs::read(&received).unwrap()).unwrap();
    assert_eq!(args, ["--env-file", env_file.to_str().unwrap()]);
    assert!(!preloaded.exists(), "the preload ran before the API tools");
}
