---
name: routing-outbound-api-calls
description: >
  Use before adding or changing Python code that calls a third-party HTTP API from PostHog (a vendor
  REST call, a vendor SDK client, a scraping or enrichment service), and before adding or changing a
  domain under posthog/egress/: its budget, priority lanes, identity, metrics, or rate-limit headers.
  Routes the call to an existing egress domain, a new gated domain, a record-only domain, or no domain
  at all, names the reference domain to copy, and lists the tests that catch a missing priority reserve.
  Trigger terms: egress, outbound API, third-party API, vendor client, rate limit, 429, Retry-After,
  budget, priority lane, BATCH, reserve, EgressClient, RecordedEgressClient, github_request.
---

# Routing outbound API calls

`posthog/egress/` owns every outbound third-party API call that needs a shared budget or telemetry.
[`posthog/egress/README.md`](../../../posthog/egress/README.md) is the reference for the mechanisms, and each domain's own `README.md` holds the facts about that API.
This skill holds the procedure and the traps.

## Route first

| Situation                                                                                                    | Route                                                                                                                  |
| ------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| A domain for the API exists (`ls posthog/egress/*/README.md`)                                                | Call its `<domain>_request` helper or typed client. Read its README for identity and lanes. Never add a second client. |
| New API, PostHog owns the credential, and the vendor publishes a request limit or bills per call             | New gated domain: `EgressClient`, or `AsyncEgressClient` for an aiohttp client                                         |
| New API, PostHog owns the credential, and the vendor publishes no request limit that a rate budget can model | New record-only domain: `RecordedEgressClient`                                                                         |
| The customer owns the credential on their own vendor account, and no PostHog process shares it               | No domain. Honor `429` and `Retry-After` at the caller. See "who owns the token" in `/implementing-warehouse-sources`. |
| Throttling requests that reach PostHog's own API                                                             | `posthog/rate_limit.py`, not egress                                                                                    |
| A budget that needs burst capacity, refunds, or a real per-caller `Retry-After`                              | `/using-redis-token-buckets`                                                                                           |
| A secret-URL webhook (a Slack incoming webhook, an interactivity `response_url`)                             | Out of scope. The URL is the credential, so it must never become a metric label.                                       |
| A vendor calls PostHog (an inbound webhook)                                                                  | `/adding-inbound-webhooks`                                                                                             |

## Decide before you write code

Write these four answers into the domain `README.md` first.
Take each answer from the vendor's documentation or from production traffic, never from a sibling domain.

1. **Identity.** The budget owner in the vendor's own id space: an installation, an account, a fleet. Never a PostHog row id. A secret identity goes through `scope_fingerprint` before it becomes a scope.
2. **Budget.** A documented vendor limit means the budget stays under it. No documented limit means an operator ceiling on spend, read from settings. When the API already has a caller, check its peak requests per scope per minute and per hour before you pick numbers.
3. **Lanes.** Keep the default reserve: `BATCH` is denied at 70% of a window, `NORMAL` at 90%. Pass `reserve={}` only when every caller runs on one lane, say why in the limiter docstring, and add the domain to `_FLAT_DOMAINS` in `posthog/egress/test/test_domains.py`. Give every caller an explicit lane: a person waiting gets `NORMAL`, background work gets `BATCH`. A call built from user-controlled input never runs `CRITICAL`, because `CRITICAL` is never shed.
4. **Headers.** Parse only the rate-limit headers the vendor documents, and declare a gauge only for those. A header with an undocumented encoding (epoch or seconds) gets no gauge.

## Source every vendor fact

A limit, a cost, a quota, a header name, or a claim that a header is absent is a vendor fact.
Each one goes into the domain `README.md` with its evidence under `## Sources`. `test_domains.py` fails a README without that section.

- **Cite the vendor's own page.** A PR description, a sibling domain, a code comment, a blog post, or a search-result summary is not a source. Open the page it points at and cite that.
- **Render docs that need JavaScript.** WebFetch returns an empty shell for a single-page docs site and can get a 429. Open the page in a headless browser (the Playwright MCP) or fetch the site's `llms-full.txt`. A docs site that renders nothing is not proof that the vendor documents nothing.
- **Write "unverified" when no source loads.** Never turn an unchecked fact into a confident sentence.
- **Check the gauges after the first deploy.** Query the domain's rate-limit gauges once the domain has traffic. An empty gauge means the headers do not reach PostHog, even when the docs say they do.
- **Rule out your own code before you blame the vendor.** Before you write that a header does not arrive, confirm three things: the recorder passes a scope, the parser reads the documented name, and the process exports other gauges.

## Build a new domain

Work through "Adding a new egress domain" in the egress README.
Copy the closest reference domain for the file layout:

| Shape                                | Reference                        |
| ------------------------------------ | -------------------------------- |
| Sync, gated, with rate-limit headers | `posthog/egress/github/`         |
| Sync, gated, no rate-limit headers   | `posthog/egress/firecrawl/`      |
| Record-only, secret identity         | `posthog/egress/vapi/`           |
| Async (aiohttp)                      | `posthog/egress/harmonic/`       |
| Vendor SDK                           | `posthog/egress/slack/client.py` |

- **Copy the layout, not the numbers.** Redo the four decisions above for the new API. A copy keeps the reference's settings defaults, lane defaults, and header names.
- **Let the base client record.** The client sets `observability = <domain>_egress`. Do not add `record_<domain>_response` wrappers.
- **Keep metric names explicit and stable.** Dashboards and alerts query them by name.
- **Keep `posthog.models` imports out of the domain package.**
- **The limiter never blocks.** The caller catches `<Domain>EgressBudgetExhausted` and backs off, defers, or degrades. A caller that folds exceptions into "not found" must catch it first.
- **A caller that walks pages paces** with `pace_seconds` and `admission_interval_seconds` instead of getting denied.

## Change an existing domain

- Update the domain `README.md` in the same PR when its identity, budget, lanes, callers, or headers change.
- Never rename a shipped metric or label.
- A move between a flat and a laned policy changes production behavior. Compare the domain's peak traffic with the new thresholds and state the result in the PR.
- A new caller of an existing domain passes its lane explicitly and goes into the domain README's callers.
- A policy registered outside `posthog/egress/` gets the same default reserve. A single-lane throttle there passes `reserve={}`.

## Tests

Invoke `/writing-tests` first. In this package, these tests earn their place:

- **Transport wiring.** Patch `requests.request` (or the aiohttp session), call the real `<domain>_request`, and assert the scope, the headers, and the recorded counter. Assert that a secret never reaches a label.
- **Settings names.** Assert `resolve_policy(key).limits` under `override_settings`. The `getattr` defaults silently swallow a misspelled setting.
- **Header parsing.** One parser case per documented header, plus garbage values.
- **Lanes, only for a domain that overrides the reserve.** Use the real policy through `OutboundRateLimiter(LimitsBackend())` and a unique key.

These do not:

- **A lane claim proven with a patched gate.** A test that patches `consume_*_sync` to return `False` passes when the policy has no reserve at all.
- **A per-domain copy of the default-ladder test.** `test_outbound_rate_limiter.py` covers the ladder, and `test_domains.py` pins the flat domains.

## Traps this package already hit

- **A fake gate.** `CRITICAL` plus a huge budget, or `_consume` that always returns `True`. Use `RecordedEgressClient` instead.
- **A missing scope.** A scope of `None` or `""` skips the gate. A single-account domain passes a constant scope such as `"default"`, or every call goes through ungated.
- **The base lane.** `EgressClient.request` defaults to `CRITICAL`. The `<domain>_request` helper sets its own sheddable default.
- **Header names guessed from another vendor.** Firecrawl shipped gauges for GitHub-style `X-RateLimit-*` names that Firecrawl never documented, and they never recorded a value.
- **A vendor fact copied from a PR description.** Open the vendor page, even when the page needs a browser to render.
- **A caller from an unmerged PR documented as if it exists.**
- **A domain added as a side effect of a product PR, with no README.** `test_domains.py` fails it. Write the README rather than skipping the test.
- **Position words and hand-kept lists in docs** ("like the two above", "the second domain"). They break when the next domain lands.
