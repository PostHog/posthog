---
cargo/posthog-cli: patch
---

Add `--upload-timeout <SECONDS>` (or `POSTHOG_CLI_UPLOAD_TIMEOUT`) for uploads to object storage. Each upload request used to stop after reqwest's 30 s default, so a large symbol set, such as a universal dSYM of over 100 MB, failed on every try from a slow uplink. The default stays 30 s.
