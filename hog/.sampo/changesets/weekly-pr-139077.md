---
npm/hog: patch
---

`hog schema pull --language golang` generates a package for posthog-go 2.x (`github.com/posthog/posthog-go/v2`) when the nearest `go.mod` requires it, and for 1.x as before otherwise. `"sdk": "posthog-go"` or `"sdk": "posthog-go-v2"` in `posthog.json` overrides `go.mod`, and `--sdk` sets it. At a terminal hog asks when neither decides. hog versions before this one reject a `golang` entry with `sdk`
