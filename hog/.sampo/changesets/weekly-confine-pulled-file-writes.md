---
npm/hog: patch
---

`schema pull` and `endpoints pull` now write only inside the project, and hog won't write through a `posthog.json` link. `error-tracking` commands refuse folders in `errorTracking.sources` outside the project, and never open a sourcemap outside the selected paths. Pass a folder outside the project on the command line.
