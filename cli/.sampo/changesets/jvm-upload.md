---
cargo/posthog-cli: minor
---

Add `jvm upload`, which uploads the Java and Kotlin sources of a build so error tracking shows source code on JVM stack frames. With `--meta-out`, it writes the id of the upload into `posthog-meta.properties` for the PostHog server SDK to send.
