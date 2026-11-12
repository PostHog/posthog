---
cargo/posthog-cli: minor
---

Add `--sdk none` to `exp schema pull --language typescript`, which generates only the event types, with no posthog-js dependency, for posthog-react-native or any other SDK. `--language` picks the language without a prompt
