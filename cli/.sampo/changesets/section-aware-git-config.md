---
cargo/posthog-cli: patch
---

Read the remote URL from the `[remote "..."]` sections of the Git config only, and prefer `origin`. A repository that records another URL in its config, such as a superproject that records the URL of a submodule, no longer gets the wrong remote URL and repository name in its release metadata.
