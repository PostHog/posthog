---
npm/hog: patch
---

`hog error-tracking clone` and `upload` now read Hermes sourcemaps in pieces, so they use about half the memory on a large React Native app.
