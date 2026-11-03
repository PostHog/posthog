---
cargo/posthog-cli: patch
---

Return a credentials error that names `POSTHOG_HOME` and the env credential variables, instead of panicking, when no home directory can be found
