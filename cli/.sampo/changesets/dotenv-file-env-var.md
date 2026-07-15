---
cargo/posthog-cli: patch
---

The dotenv credentials file can now also be pointed at with the `POSTHOG_CLI_DOTENV_FILE` environment variable, equivalent to passing `--dotenv-file` — for callers that control the environment but not the command line (e.g. an Xcode build phase invoking the iOS SDK's upload-symbols.sh).
