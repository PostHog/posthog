---
cargo/posthog-cli: patch
---

Stop shipping an npm-shrinkwrap.json in the npm package, so installing `@posthog/cli` no longer adds its own `prettier` to the project's `node_modules` and `package-lock.json`
