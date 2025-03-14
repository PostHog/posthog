# Products

This file contains PostHog products. 

- Internal RFC: https://github.com/PostHog/product-internal/pull/703
- Mergerd in PR: https://github.com/PostHog/posthog/pull/26693

## Dev guidelines

- Please keep the folder names `under_score` cased, as dashes make it hard to import files in some languages (e.g. Python, Ruby, ...)
- Inside the product folder, have a `manifest.tsx` file to describe your product's routes and capabilities, and a `package.json` to register it with the build tooling.
- The manifests are all merged into one `frontend/src/products.tsx` at build time by esbuild.
- Separat your product's backend and frontend into `backend` and `frontend` folders if necessary.