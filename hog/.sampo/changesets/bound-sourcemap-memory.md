---
npm/hog: patch
---

`hog error-tracking inject`, `process` and `upload` now handle one JavaScript bundle and its sourcemap at a time, so their memory use no longer grows with the size of the build.
