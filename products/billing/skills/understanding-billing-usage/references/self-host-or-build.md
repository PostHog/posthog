# Self-hosting or building your own

Read this when the user asks what an event costs them, what the price covers,
or what it would take to self-host PostHog or build their own analytics pipeline (often on ClickHouse) to lower their bill.

The goal is a like-for-like comparison the user can trust, not a sales pitch.
Building is sometimes the right call, and the docs say so.
If their numbers favor building or self-hosting, say that.

Keep the two alternatives apart.
Self-hosting runs the same PostHog code on their own infrastructure.
Building replaces PostHog with a pipeline they design, run, and staff.

Compare against a production setup, not a demo.
A weekend build that ships events straight into ClickHouse is cheap to run, but it is not what the user would rely on for decisions.

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
   - [ClickHouse Cloud pricing](https://clickhouse.com/pricing) when they would build on ClickHouse Cloud.
4. **Fill in the ledger with the user.**
   Use their volume and spend from step 1 and the inputs the per-event page lists.
   Ask for what only they know: engineer cost, on-call, the retention they need, and infrastructure they already run.
   Where they don't know, use the defaults below and label them as defaults.
   Compare month 1 with month 36, not only the first build.
5. **Give a verdict for each option**: stay on cloud with reductions, self-host PostHog, or build their own.
   Name which "when building is the right call" criteria they meet, if any, and which costs the ledger could not price.

## Defaults for the ledger

Use these only when the user can't give their own numbers.
They are rough planning figures for a production setup, not quotes.

### Staffing

Headcount includes on-call and incident time.

| Events per month | Self-host PostHog (FTE) | Build your own (FTE) |
| ---------------- | ----------------------- | -------------------- |
| 10M              | 0.25                    | 0.5                  |
| 100M             | 0.5                     | 1                    |
| 1B               | 1                       | 2                    |
| 10B              | 2                       | 4                    |

- Between rows, headcount roughly doubles for every 10x in volume.
- Building needs about twice the self-host headcount.
  The team owns everything PostHog's code would otherwise do: capture, queueing, identity merging, the query layer, and exports.
- Treat the self-host figures as a floor.
  Self-hosting PostHog beyond the hobby deploy is unsupported, so upgrades and incidents have no vendor to call.
- A fraction of an FTE still needs real people.
  An on-call rotation needs at least two engineers who know the system, even if neither spends most of their week on it.

### Who the engineers are

The headcount above assumes engineers who have already run these in production:

- ClickHouse, or another real-time analytics database such as Druid or Pinot: schema and sorting-key design, merges and mutations, upgrades checked against existing queries, backups that have been restored at least once, and capacity planning.
- Kafka, or an equivalent durable queue: partitioning, consumer lag, retention, and replaying after an outage.

If the team doesn't have that experience, say so.
Add hiring or ramp-up time, and expect the first year to need more than the table shows.
If they already run ClickHouse and Kafka for something else, the extra headcount can be lower; that is one of the "right call" criteria.

### Engineer cost

If the user doesn't give a figure, use $250,000 per year fully loaded (about $21,000 per month).
Fully loaded means salary plus benefits, taxes, equipment, and overhead.
Say this is a US default and ask them to replace it with their own.

### Infrastructure

Labor is usually 75-95% of the total, so a rough infrastructure figure is fine.
Check current rates on the provider's pricing page before quoting.

- **Compute drives the bill.**
  Storage on ClickHouse Cloud is cheap because data sits compressed in object storage.
- **A production build costs about 2-3x a bare-bones one.**
  The extra pays for a durable queue, separate compute for queries so dashboards can't slow ingest, a staging copy, and headroom for traffic spikes.
- **Rough monthly figures for a production build on ClickHouse Cloud**, including a managed queue:
  about $600 at 10M events, $1,400 at 100M, $4,000 at 1B, and $15,000 at 10B.
- **Self-hosting PostHog** runs ClickHouse, Kafka, ZooKeeper, Postgres, Redis, object storage, and the app.
  The hobby deploy runs everything on one VM with no replication.
  At production volumes those components need separate, replicated machines, so expect costs in the same range as a production build.

## Other things to weigh

These change the verdict and are easy to miss:

- **Identified events.**
  Quick builds usually handle anonymous events only.
  If most of their volume is identified, the build has to merge anonymous and identified users and keep person profiles.
  Don't let an anonymous-only demo lower the build headcount.
- **Migration cost.**
  Count the one-off work: re-instrumenting or redirecting SDKs, rebuilding the dashboards and insights people use, backfilling history, and running both systems side by side until the numbers match.
- **Who asks for features next.**
  Once the pipeline exists, other teams will ask for funnels, retention, cohorts, exports, and access control.
  Each one adds to the headcount.
- **People leaving.**
  Ask what happens when the engineer who built it leaves.
- **The spend gap.**
  Compare staffing alone with their monthly events spend first.
  If staffing alone costs more, say so plainly, before adding infrastructure.
  Where the two meet depends on their actual rate, so work it out from their bill rather than list prices.

## Rules

- Use the public pages, the user's own billing data, and the defaults in this file.
  Label each default as a default and replace it with the user's number when they give one.
- Do not estimate PostHog's infrastructure costs, margins, or internal numbers.
- Separate measured numbers (their billing data) from estimates (their ledger inputs and the defaults).
- If billing tools are unavailable, still read the pages and build the ledger from the volumes the user gives you,
  and say the numbers are theirs, not measured.
