use std::{
    io::{Read, Write},
    net::TcpListener,
    process::Command,
    time::Duration,
};

#[test]
fn task_failures_show_posthog_details_only_outside_ci_and_never_raw_bodies() {
    let drf = r#"{"type":"validation_error","code":"invalid","detail":"DETAIL_VALUE","attr":"ATTR_VALUE"}"#;

    for (body, in_ci, shows_detail) in [
        ("BODY_SECRET", false, false),
        ("BODY_SECRET", true, false),
        (drf, false, true),
        (drf, true, false),
    ] {
        let output = run_task_progress(body, in_ci);
        let stderr = String::from_utf8_lossy(&output.stderr);

        assert!(!output.status.success(), "{stderr}");
        assert!(stderr.contains("500"), "{stderr}");
        assert!(stderr.contains("/progress/"), "{stderr}");
        for secret in ["HOST_SECRET", "COOKIE_SECRET", "BODY_SECRET"] {
            assert!(!stderr.contains(secret), "{stderr}");
        }
        assert_eq!(
            stderr.contains("details='DETAIL_VALUE'"),
            shows_detail,
            "in_ci={in_ci}: {stderr}"
        );
        assert_eq!(
            stderr.contains("hidden in CI"),
            in_ci && body == drf,
            "in_ci={in_ci}: {stderr}"
        );
    }
}

fn run_task_progress(body: &'static str, in_ci: bool) -> std::process::Output {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut request = Vec::new();
        let mut byte = [0];
        while !request.ends_with(b"\r\n\r\n") {
            assert_eq!(stream.read(&mut byte).unwrap(), 1);
            request.push(byte[0]);
        }
        write!(stream, "HTTP/1.1 500 Internal Server Error\r\nSet-Cookie: session=COOKIE_SECRET\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
    });

    let home = tempfile::tempdir().unwrap();
    let mut command = Command::new(env!("CARGO_BIN_EXE_posthog-cli"));
    command
        .env_clear()
        .env("HOME", home.path())
        .env("POSTHOG_HOME", home.path())
        .env("POSTHOG_CLI_API_KEY", "phx_dummy")
        .env("POSTHOG_CLI_PROJECT_ID", "1")
        .env(
            "POSTHOG_CLI_HOST",
            format!("http://user:HOST_SECRET@{address}"),
        )
        .env("RUST_LOG", "posthog_cli=debug")
        .args([
            "exp",
            "task",
            "progress",
            "11111111-2222-4333-8444-555555555555",
        ]);
    if in_ci {
        command.env("CI", "true");
    }
    let output = command.output().unwrap();

    server.join().unwrap();
    output
}

#[test]
fn endpoint_debug_shows_payloads_only_outside_ci_without_changing_requests_or_results() {
    for in_ci in [true, false] {
        let (request, output) = run_endpoint_with_debug(in_ci);
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout = String::from_utf8_lossy(&output.stdout);

        assert!(output.status.success(), "{stderr}");
        assert_eq!(request["variables"]["api_token"], "REQUEST_SECRET");
        assert!(stdout.contains("RESULT_SECRET"), "{stdout}");
        assert!(stderr.contains("POST"), "{stderr}");
        for secret in ["REQUEST_SECRET", "RESULT_SECRET"] {
            assert_eq!(stderr.contains(secret), !in_ci, "in_ci={in_ci}: {stderr}");
        }
    }
}

fn run_endpoint_with_debug(in_ci: bool) -> (serde_json::Value, std::process::Output) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(5)))
            .unwrap();
        let mut head = Vec::new();
        let mut byte = [0];
        while !head.ends_with(b"\r\n\r\n") {
            assert_eq!(stream.read(&mut byte).unwrap(), 1);
            head.push(byte[0]);
        }
        let head = String::from_utf8(head).unwrap();
        let length = head
            .lines()
            .find_map(|line| {
                let (key, value) = line.split_once(':')?;
                key.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().unwrap())
            })
            .unwrap();
        let mut request = vec![0; length];
        stream.read_exact(&mut request).unwrap();
        let body = r#"{"results":[["RESULT_SECRET"]],"columns":["value"]}"#;
        write!(stream, "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len()).unwrap();
        request
    });

    let home = tempfile::tempdir().unwrap();
    let file = home.path().join("endpoint.yaml");
    std::fs::write(&file, "name: demo\nquery: SELECT 1\n").unwrap();
    let mut command = Command::new(env!("CARGO_BIN_EXE_posthog-cli"));
    command
        .env_clear()
        .env("HOME", home.path())
        .env("POSTHOG_HOME", home.path())
        .env("POSTHOG_CLI_API_KEY", "phx_dummy")
        .env("POSTHOG_CLI_PROJECT_ID", "1")
        .env("POSTHOG_CLI_HOST", format!("http://{address}"))
        .args(["exp", "endpoints", "run", "--file"])
        .arg(file)
        .args(["--var", "api_token=REQUEST_SECRET", "--debug", "--json"]);
    if in_ci {
        command.env("CI", "true");
    }
    let output = command.output().unwrap();

    let request = serde_json::from_slice(&server.join().unwrap()).unwrap();
    (request, output)
}
