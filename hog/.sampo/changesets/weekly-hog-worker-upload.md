---
npm/hog: patch
---

`hog error-tracking upload` and `process` now build JavaScript and ProGuard symbol sets in hog-worker, and `--delete-after` cleans up there too. The uploads and the files are the same, and a large build takes far less time and memory.
