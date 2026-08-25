---
title: Managed reverse proxy
sidebar: Docs
showTitle: true
---

PostHog can manage a reverse proxy on a custom domain. After you add the required CNAME record, PostHog provisions the proxy and keeps its certificate up to date.

## Redirect the proxy root

You can redirect requests to the root of a Cloudflare-managed proxy, such as `https://e.example.com/`, to another URL. The redirect does not affect event ingestion or other paths on the proxy.

To add a redirect:

1. Go to **Settings > Environment > Managed reverse proxy**.
2. Expand a proxy that has a **Live** or **Warning** status.
3. Select **Root redirect**.
4. Enter the destination URL and select **Save redirect**.

The destination must:

- Use HTTPS.
- Use the same registered domain as the proxy. For example, `e.example.com` can redirect to `example.com` or `www.example.com`.
- Not point back to the managed proxy domain.
- Not include a username or password.

To remove the redirect, clear the destination URL and select **Save redirect**. Requests to the proxy root then use the default proxy behavior.

Root redirects are available only for Cloudflare-managed proxies. If the setting is not shown, confirm that the proxy is managed by PostHog and has a **Live** or **Warning** status.
