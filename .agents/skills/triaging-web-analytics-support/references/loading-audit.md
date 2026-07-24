# Runtime loading audit

Verifies what actually happens when a browser loads the customer's site: which trackers load, via what delivery chain, how late, and what an ad blocker changes.
This is the check the wizard's audit mode does NOT do (it is a static code review of the customer's repo) — a live-site audit is the only way to see GTM, consent, and blocker effects.

## Pattern

Playwright (Chromium), two passes over 2-4 representative URLs (landing page, one deep page, one with UTM params):

1. **Normal pass**: real-user UA, US locale/timezone. Record every request to tracker domains with a timestamp relative to navigation start. After load + ~10s, evaluate in-page state: `window.posthog` (`__loaded`, `config.api_host`, `config.token` prefix, `person_profiles`), tag-manager containers and `dataLayer` length, consent platform object and its resolved state, competitor tracker globals and script tags.
2. **Blocklist pass**: same, but abort requests matching an EasyPrivacy-style domain list (`googletagmanager.com`, `google-analytics.com`, analytics vendor domains). Compare which trackers survive.

What to read from the results:

- **Load method**: `<head>` snippet vs tag manager vs bundled. A proxied `api_host` with GTM delivery still dies when GTM is blocked — the delivery chain is the weakest link.
- **First-request delta**: tracker's first network activity in ms after navigation, vs the competitor's. The gap is the quick-bounce blind window.
- **Consent geo-gating**: consent platforms often don't load at all outside GDPR regions; delay in those regions is tag-manager boot, not the banner.

## Caveats

- **Both major SDKs suppress automation**: posthog-js and most competitors detect `navigator.webdriver` and do not send events from headless browsers. Zero capture requests in the audit is expected and says nothing about real users. Assert on script/runtime presence and timing, not on event POSTs.
- A visit with `?utm_...` test params is harmless; never inject fabricated conversion events into a customer's project.
- Numeric hostnames parse as IPv4 in `new URL()` — don't assert exact parsed hosts on synthetic inputs.

## Prior art

- Session-scoped audit script: written fresh per audit (~120 lines); an earlier full-featured CLI (`check-loading`, `new-user`, `returning-user` scenarios) lives in an internal sandbox repo with an open plan to publish as `tools/traffic-sim/`.
- A per-page comparison table (load method, snippet location, config key/host, match vs baseline) makes partial-migration states obvious — pages missing the tracker entirely show up immediately.
