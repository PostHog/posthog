---
cargo/posthog-cli: patch
---

An empty `POSTHOG_CLI_API_KEY`, `POSTHOG_CLI_PROJECT_ID` or `POSTHOG_CLI_HOST` variable now counts as unset, so the CLI uses the next credential source instead of failing. CI systems often set a secret that a job cannot read to an empty string.
