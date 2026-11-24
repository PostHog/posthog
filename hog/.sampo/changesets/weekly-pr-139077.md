---
npm/hog: patch
---

`hog schema pull --language golang` generates a package for posthog-go 2.x (`github.com/posthog/posthog-go/v2`) when the nearest `go.mod` requires it, and for 1.x as before otherwise. `--sdk posthog-go` or `--sdk posthog-go-v2` overrides that for one run, and at a terminal hog asks when no `go.mod` decides. `posthog.json` gets no new setting, so older hog versions keep working with it
