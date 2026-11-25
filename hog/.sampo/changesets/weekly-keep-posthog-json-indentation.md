---
npm/hog: patch
---

hog keeps the indentation and the trailing newline of posthog.json when it updates the file, as `hog auth login` and `hog schema pull` do.
