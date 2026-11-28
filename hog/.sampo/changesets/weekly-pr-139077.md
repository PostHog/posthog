---
npm/hog: patch
---

`hog schema pull --language golang` generates posthog-go 2.x code when the nearest `go.mod` requires it. `"sdk"` in `posthog.json` or `--sdk` overrides that
