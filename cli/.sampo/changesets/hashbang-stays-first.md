---
cargo/posthog-cli: patch
---

Inject the chunk id snippet after a leading hashbang (`#!/usr/bin/env node`) instead of in front of it. A hashbang is only valid as the first line of a script, so injected Node CLI bundles failed to start with `SyntaxError: Invalid or unexpected token`.
