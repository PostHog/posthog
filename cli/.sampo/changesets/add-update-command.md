---
cargo/posthog-cli: patch
---

Add `posthog-cli update`. It updates in place when you installed with the install script, and prints the right command when npm, Homebrew or cargo owns the binary. The old `posthog-cli-update` is no longer installed; it could not reach a release and never worked.
