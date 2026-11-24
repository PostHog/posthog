---
npm/hog: patch
---

Every install of hog now includes hog-worker, the program that reads and writes build output for `hog error-tracking`, and `hog upgrade` and the install scripts replace the two together. On Alpine and other musl systems, the install script now names the missing `libstdc++` and `libgcc` packages when hog can't start without them.
