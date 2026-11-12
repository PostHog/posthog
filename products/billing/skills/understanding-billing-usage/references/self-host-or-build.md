# Self-hosting or building your own

Read this when the user asks what an event costs them, what the price covers,
or what it would take to self-host PostHog or build their own analytics pipeline (often on ClickHouse) to lower their bill.

The goal is a like-for-like comparison the user can trust, not a sales pitch.
Building is sometimes the right call, and the docs say so.
If their numbers favor building or self-hosting, say that.

Keep the two alternatives apart.
Self-hosting runs the same PostHog code on their own infrastructure.
Building replaces PostHog with a pipeline they design, run, and staff.

## Workflow

1. **Get their real numbers.**
   Call `posthog:billing-spend-get` and `posthog:billing-usage-get` for the last three months with `breakdowns: ["type"]`.
   Note which products drive spend and how much of the event volume is identified.
   A pipeline that only replaces product analytics events leaves replay, flags, and the other products on the bill.
   If they are inside the free tier, their events cost nothing; say so first.
2. **Look for waste before comparing.**
   If one project, event, or usage type drives most of the spend, follow the reduction path in `SKILL.md`.
   Cutting autocapture noise, extra `identify()` calls, or stale flag traffic can close the gap on its own.
3. **Read the live pages.**
   Do not quote prices, retention, limits, or support terms from memory.
   - [What you actually get when you pay for an event](https://posthog.com/docs/billing/what-you-pay-for-per-event.md):
     what the price covers, the build-it-yourself table, costs that arrive later, the ledger, and when building is the right call.
   - [Self-host PostHog](https://posthog.com/docs/self-host.md) and its support disclaimer, for the self-hosting option.
   - [Pricing](https://posthog.com/pricing) and the product's cutting-costs page for current rates and reductions.
4. **Fill in the ledger with the user.**
   Use their volume and spend from step 1 and the inputs the per-event page lists.
   Ask for what only they know: engineer cost, on-call, the retention they need, and infrastructure they already run.
   Label each assumption, and compare month 1 with month 36, not only the first build.
5. **Give a verdict for each option**: stay on cloud with reductions, self-host PostHog, or build their own.
   Name which "when building is the right call" criteria they meet, if any, and which costs the ledger could not price.

## Rules

- Use only the public pages and the user's own billing data.
  Do not estimate PostHog's infrastructure costs, margins, or internal numbers.
- Separate measured numbers (their billing data) from estimates (their ledger inputs).
- If billing tools are unavailable, still read the pages and build the ledger from the volumes the user gives you,
  and say the numbers are theirs, not measured.
