---
title: Cookie banner
sidebar: Docs
showTitle: true
---

> 🚧 **Note:** The cookie banner is in alpha, gated behind the `cookie-banner` feature flag.

PostHog can show a cookie consent banner on your website, so you don't need a separate consent vendor to stay compliant.
Visitors' choices are wired straight into PostHog tracking consent: accepting calls `posthog.opt_in_capturing()` and declining calls `posthog.opt_out_capturing()`.
The banner is styled after the PostHog cookie banner by default, and you can tailor the text, colors, position, and art, including PostHog hedgehog art.
It can also localize its copy per language, offer a per-category preferences panel, fall back to cookieless analytics on decline, and respect the Global Privacy Control signal.

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

Once a visitor makes a choice, it is stored in their browser (`localStorage` key `__ph_cookie_banner_consent`, with a `__Host-` prefixed cookie fallback on HTTPS) and the banner doesn't show again.

You can also manage the banner through the [PostHog MCP](/docs/model-context-protocol) with the `cookie-banner-list`, `cookie-banner-create`, and `cookie-banner-partial-update` tools, or query it via SQL from the `system.cookie_banner_configs` table.

## Gating other scripts on consent

The banner dispatches a `posthog:consent` event on `window` when a visitor makes a choice, and again on every page load once a choice is stored.
Use it to gate your other analytics or marketing scripts:

```js
window.addEventListener('posthog:consent', (event) => {
  // event.detail.status is 'accepted' or 'declined'
  // event.detail.source is 'user' (just clicked), 'stored' (returning visitor),
  // or 'gpc' (auto-declined by Global Privacy Control)
  // event.detail.categories is { analytics: boolean, marketing: boolean }
  if (event.detail.categories.marketing) {
    // load your marketing scripts here
  }
})
```

## Consent options

- **Manage preferences**: adds a link that opens a panel where visitors consent to analytics and marketing cookies separately.
  Analytics consent controls PostHog tracking; the marketing choice reaches your site through the `posthog:consent` event so you can gate your own scripts.
- **Cookieless fallback on decline**: instead of stopping tracking entirely, a decline switches posthog-js to in-memory persistence.
  Nothing is stored on the visitor's device and each page load starts a fresh anonymous session, so you keep privacy-safe traffic counts.
- **Respect Global Privacy Control** (on by default): visitors whose browser broadcasts the [GPC signal](https://globalprivacycontrol.org/) are treated as declined and never shown the banner.
  An explicit choice made on your site still takes precedence.

## Languages

Add languages in the **Languages** section to serve translated copy based on the visitor's browser language (`navigator.language`).
An exact match like `pt-BR` wins over a base-language match like `pt`; fields you leave empty fall back to the default copy.

## Banner analytics

The banner captures `cookie banner accepted` and `cookie banner declined` events into your project (with the chosen categories and seconds to decision) so you can chart accept rates.
Nothing is captured before the visitor's explicit choice — there is deliberately no impression event, since it would have to be sent pre-consent.
`declined` events go through the normal posthog-js consent gate, so they only arrive when the cookieless fallback is enabled.

## Removing the "Powered by PostHog" notice

The banner shows a small "Powered by PostHog" notice.
You can remove it with the **Hide PostHog branding** option if your plan includes the white labelling feature, the same entitlement that removes branding from surveys and shared dashboards.

## Compliance

The banner gives your visitors a clear accept or decline choice for tracking, and PostHog respects that choice.
Consent requirements vary by jurisdiction and by what your site does, so review your setup with your own legal counsel.
