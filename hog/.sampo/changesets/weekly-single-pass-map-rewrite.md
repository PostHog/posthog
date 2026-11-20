---
npm/hog: patch
---

`hog error-tracking inject` and `process` now rewrite each sourcemap in one pass, so they need about a third of the memory on large bundles and run faster.
