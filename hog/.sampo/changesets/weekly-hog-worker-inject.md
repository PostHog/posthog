---
npm/hog: patch
---

`hog error-tracking inject` now rewrites bundles and sourcemaps in hog-worker, a Rust program that ships next to hog. The files it writes are the same, and a large build takes far less time and memory.
