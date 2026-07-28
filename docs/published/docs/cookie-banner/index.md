---
title: Cookie banner
sidebar: Docs
showTitle: true
---

> 🚧 **Note:** The cookie banner is in alpha, gated behind the `cookie-banner` feature flag.

PostHog can show a cookie consent banner on your website and manage what the visitor's choice applies to: PostHog tracking, your other scripts, and Google tags.
The banner loads before posthog-js and before any script it gates, so nothing it manages runs until the visitor has chosen.
It is styled after the PostHog cookie banner by default, and you can tailor the text, consent categories, colors, position, and art, including PostHog hedgehog art.
It also localizes its copy per language, offers a per-category preferences panel, can fall back to cookieless analytics on decline, supports Google Consent Mode v2, and respects the Global Privacy Control signal.

The banner is a tool you configure, not a compliance service.
It doesn't make your site compliant on its own, and PostHog doesn't provide legal advice.
See [What this does and doesn't do](#what-this-does-and-doesnt-do).

## Install

1. Open **Cookie banner** in PostHog, tailor the text and appearance, and enable it. There is one banner per project.
2. Add the consent script as the first script tag on your page, before the PostHog snippet and before any script it should gate:

```html
<script src="<your API host>/array/<your project API key>/cookie-banner.js"></script>
```

3. Keep your PostHog snippet below it, with these init options:

```js
posthog.init('<your project API key>', {
  api_host: '<your API host>',
  opt_out_capturing_by_default: true, // no events before consent
  opt_out_persistence_by_default: true, // no cookies or localStorage before consent
})
```

The consent script must load synchronously (no `async` or `defer`) and before everything else.
That ordering is what guarantees the Google Consent Mode default lands before your Google tags, blocked scripts stay blocked, and posthog-js sees the visitor's stored choice the moment it initializes.

After you enable the banner for the first time, allow up to 10 minutes for caches to pick it up.

## What happens before consent

- The consent script itself is a static, per-project file. Serving it stores nothing about the visitor.
- On the first visit, no choice exists yet. The script writes posthog-js's consent record (`__ph_opt_in_out_<project API key>`) as opted out before the SDK loads. This protects pending visitors: the record's name derives from your public project API key, so without the seed a cookie planted from another subdomain could opt a visitor in before they choose. It also means the banner overrides consent state written by any earlier consent setup until the visitor chooses.
- With the init options above, posthog-js captures no events before consent. The one exception is the feature flags request, which posthog-js sends on load with an anonymous id; set `advanced_disable_flags: true` to stop it, at the cost of feature flags not working on that site.
- On a return visit, the script reads the stored choice and applies it before posthog-js initializes, so the SDK boots already opted in or out.
- Before a choice, the opted-out consent record above is the only thing the banner writes. The choice itself (`localStorage` key `__ph_cookie_banner_consent`, with a `__Host-` prefixed cookie fallback on HTTPS) is written when the visitor decides.

## Blocking your other scripts

To keep a script from running until the visitor grants a category, change its `type` to `text/plain` and add a `data-ph-consent` attribute with one or more category keys:

```html
<script type="text/plain" data-ph-consent="marketing" src="https://example.com/ad-pixel.js"></script>
<script type="text/plain" data-ph-consent="analytics marketing">
  // inline scripts work too; this one needs both categories granted
</script>
```

Blocked scripts activate as soon as their categories are granted: immediately on a live choice, and on page load for returning visitors.
Scripts your code injects dynamically after the choice are not scanned; gate those with the `posthog:consent` event instead.

## Consent categories

Categories are what visitors grant or deny, individually in the preferences panel or all at once with Accept and Decline.
Configure them in the **Consent categories** section: each has a key (used in `data-ph-consent` and the `posthog:consent` event), a label, and an optional description.

- `analytics` is required. It controls PostHog tracking.
- `necessary` is implicit and always-on. It appears in the preferences panel but can't be declined.
- You can add up to 10 categories, for example `chat` or `personalization`.

If you add a category after visitors have already chosen, it counts as denied for them until they choose again.

## Google Consent Mode v2

Turn on **Google Consent Mode v2** in the consent options to integrate with Google tags (gtag.js, Google Ads, GA4).
The banner pushes a denied default into the `dataLayer` before your Google tags run, then an update when the visitor chooses:

- the `analytics` category maps to `analytics_storage`
- the `marketing` category maps to `ad_storage`, `ad_user_data`, and `ad_personalization`

Remove any hand-rolled `gtag('consent', 'default', ...)` call from your site, and keep the consent script above your Google tags.
Custom category keys have no Google mapping.

## Reacting to consent in your own code

The banner dispatches a `posthog:consent` event on `window` when a visitor makes a choice, and again on every page load once a choice is stored:

```js
window.addEventListener('posthog:consent', (event) => {
  // event.detail.status is 'accepted' or 'declined'
  // event.detail.source is 'user' (just clicked), 'stored' (returning visitor),
  // or 'gpc' (auto-declined by Global Privacy Control)
  // event.detail.categories is an object like { analytics: true, marketing: false }
  if (event.detail.categories.marketing) {
    // load your marketing scripts here
  }
})
```

## Consent options

- **Manage preferences**: adds a link that opens a panel where visitors grant or deny each category separately.
- **Cookieless fallback on decline**: instead of stopping tracking entirely, a decline switches posthog-js to in-memory persistence.
  Nothing is stored on the visitor's device and each page load starts a fresh anonymous session, so you keep privacy-safe traffic counts.
  This needs the `window.posthog` snippet; it doesn't work with npm-only installs.
- **Respect Global Privacy Control** (on by default): visitors whose browser broadcasts the [GPC signal](https://globalprivacycontrol.org/) are treated as declined and never shown the banner.
  An explicit choice made on your site still takes precedence.

## Languages

Add languages in the **Languages** section to serve translated copy based on the visitor's browser language (`navigator.language`).
An exact match like `pt-BR` wins over a base-language match like `pt`; fields you leave empty fall back to the default copy.

## Banner analytics

The banner captures `cookie banner accepted` and `cookie banner declined` events into your project (with the chosen categories and seconds to decision) so you can chart accept rates.
Nothing is captured before the visitor's explicit choice. There is deliberately no impression event, since it would have to be sent pre-consent.
`declined` events only arrive when the cookieless fallback is enabled, since a plain decline opts the SDK out.

You can also manage the banner through the [PostHog MCP](/docs/model-context-protocol) with the `cookie-banner-list`, `cookie-banner-create`, and `cookie-banner-partial-update` tools, or query it via SQL from the `system.cookie_banner_configs` table.

## Removing the "Powered by PostHog" notice

The banner shows a small "Powered by PostHog" notice.
You can remove it with the **Hide PostHog branding** option if your plan includes the white labelling feature, the same entitlement that removes branding from surveys and shared dashboards.

## Limitations

- If you configured a custom `consent_persistence_name` (or the deprecated `opt_out_capturing_cookie_prefix`) in posthog-js, the banner's consent record won't match it. Remove the custom name to use the banner.
- Consent applies per host. A choice made on `www.example.com` doesn't carry over to `app.example.com`.
- With npm-only posthog-js installs (no `window.posthog`), the stored-choice gating still works through the consent record, but the cookieless fallback and banner analytics events don't.

## What this does and doesn't do

The banner shows your visitors a consent choice, honors it in PostHog, blocks the scripts you mark, and signals Google tags.
It doesn't inventory your cookies, block scripts you haven't marked, or judge what consents and disclosures the laws in your jurisdiction require.
Configuring it to meet those requirements is your responsibility, and PostHog doesn't provide legal advice.
Review your setup with your own legal counsel.
