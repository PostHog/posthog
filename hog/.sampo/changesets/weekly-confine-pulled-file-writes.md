---
npm/hog: patch
---

hog now writes pulled schema and endpoint files only inside the project, won't write through a `posthog.json` link, and skips sourcemaps outside the selected paths, so files in a repository cannot make it change files elsewhere.
