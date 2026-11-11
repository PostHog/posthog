---
cargo/posthog-cli: patch
---

Remove the `--env-file` alias of `--dotenv-file`. Use `--dotenv-file` or `POSTHOG_CLI_DOTENV_FILE` instead. `posthog-cli api` now starts the API tools with `node --`.
