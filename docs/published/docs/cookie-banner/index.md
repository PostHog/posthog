---
title: Cookie banner
sidebar: Docs
showTitle: true
---

> 🚧 **Note:** The cookie banner is in alpha, gated behind the `cookie-banner` feature flag.

PostHog can show a cookie consent banner on your website, so you don't need a separate consent vendor to stay compliant.
Visitors' choices are wired straight into PostHog tracking consent: accepting calls `posthog.opt_in_capturing()` and declining calls `posthog.opt_out_capturing()`.
The banner is styled after the PostHog cookie banner by default, and you can tailor the text, colors, position, and art, including PostHog hedgehog art.

## Setup

1. Open **Cookie banner** in PostHog, tailor the text and appearance, and enable it. There is one banner per project.
2. Make sure your site initializes posthog-js with these options:

```js
posthog.init('<your project API key>', {
  api_host: '<your API host>',
  opt_in_site_apps: true, // required: allows the cookie banner to run
  opt_out_capturing_by_default: true, // recommended: no tracking before consent
})
```

The banner is delivered through your existing PostHog snippet.
No extra script tag is needed.

Once a visitor makes a choice, it is stored in their browser (`localStorage` with a cookie fallback, key `__ph_cookie_banner_consent`) and the banner doesn't show again.

You can also manage the banner through the [PostHog MCP](/docs/model-context-protocol) with the `cookie-banner-list`, `cookie-banner-create`, and `cookie-banner-partial-update` tools, or query it via SQL from the `system.cookie_banner_configs` table.

## Gating other scripts on consent

The banner dispatches a `posthog:consent` event on `window` when a visitor makes a choice, and again on every page load once a choice is stored.
Use it to gate your other analytics or marketing scripts:

```js
window.addEventListener('posthog:consent', (event) => {
  // event.detail.status is 'accepted' or 'declined'
  // event.detail.source is 'user' (just clicked) or 'stored' (returning visitor)
  if (event.detail.status === 'accepted') {
    // load your other analytics or marketing scripts here
  }
})
```

## Removing the "Powered by PostHog" notice

The banner shows a small "Powered by PostHog" notice.
You can remove it with the **Hide PostHog branding** option if your plan includes the white labelling feature, the same entitlement that removes branding from surveys and shared dashboards.

## Compliance

The banner gives your visitors a clear accept or decline choice for tracking, and PostHog respects that choice.
Consent requirements vary by jurisdiction and by what your site does, so review your setup with your own legal counsel.
