---
npm/hog: patch
---

Add `--sdk posthog-go-v2` to `hog schema pull --language golang`, which generates a package that imports posthog-go 2.x (`github.com/posthog/posthog-go/v2`). Without it, the package imports posthog-go 1.x, as before
