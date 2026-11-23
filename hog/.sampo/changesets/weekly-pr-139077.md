---
npm/hog: patch
---

Add `--sdk posthog-go-v2` to `hog schema pull --language golang`, which generates a package that imports posthog-go 2.x (`github.com/posthog/posthog-go/v2`). In a terminal, hog asks which posthog-go version a new Go module is for. Without the flag or an answer, and for Go modules already in `posthog.json`, the package imports posthog-go 1.x, as before
