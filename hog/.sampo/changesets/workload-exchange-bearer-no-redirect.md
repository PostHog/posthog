---
npm/hog: patch
---

In CI, hog now accepts a workload token from PostHog only when its `token_type` is `Bearer`, and it stops with an error when PostHog answers the exchange with a redirect, instead of sending the job's OIDC token to the new address. Renewing a login and `hog auth logout` also no longer send the refresh token to a redirect target.
