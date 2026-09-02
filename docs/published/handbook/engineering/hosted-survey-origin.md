---
title: Hosted survey origin
sidebar: Handbook
showTitle: true
---

Hosted surveys can render customer-configured content, so PostHog Cloud must serve them on a cookie-isolated origin.

Set `SURVEYS_PUBLIC_URL` to the public origin that proxies hosted survey pages. The origin must use a different registrable domain from `SITE_URL`; a sibling subdomain is insufficient because cookies scoped to the parent domain are sent to both hosts.

When configured, PostHog:

- generates share and embed links from `SURVEYS_PUBLIC_URL`
- redirects legacy app-origin hosted survey links before rendering survey content
- removes every `Set-Cookie` header from responses served on the public survey host

The proxy must route `/external_surveys/*` to Django and the SDK asset and capture paths used by the hosted page to their existing services. Keep the setting empty for local development and self-hosted deployments that do not configure a separate origin.
