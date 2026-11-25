---
npm/hog: patch
---

In CI, hog now accepts a workload token from PostHog only when its `token_type` is `Bearer`, and it stops with an error when PostHog answers the exchange with a redirect, instead of sending the job's OIDC token to the new address. Logging in, renewing a login and `hog auth logout` also stop on a redirect instead of sending the device code or refresh token to the new address.
