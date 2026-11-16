# Self-hosting or building your own

Read this when the user asks what an event costs them, what the price covers,
or what it would take to self-host PostHog or build their own analytics pipeline (often on ClickHouse) to lower their bill.

The goal is a like-for-like comparison the user can trust, not a sales pitch.
Building is sometimes the right call, and the docs say so.
If their numbers favor building or self-hosting, say that.

Keep the two alternatives apart.
Self-hosting runs the same PostHog code on their own infrastructure.
Building replaces PostHog with a pipeline they design, run, and staff.
A third variant is sending events to a warehouse and BI tool the team already runs; see "If they already run a warehouse and BI tool" below.

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
   Always ask for their engineer cost and where the engineers are based; see "Engineer cost".
   Where they don't know, use the defaults below and label them as defaults.
   Compare month 1 with month 36, not only the first build.
5. **Work out the break-even headcount.**
   Follow "Break-even headcount" below and lead the comparison with it.
   It uses their bill, so it holds even if they disagree with the staffing defaults.
6. **Give a verdict for each option**: stay on cloud with reductions, self-host PostHog, or build their own.
   Name which "when building is the right call" criteria they meet, if any, and which costs the ledger could not price.

## Break-even headcount

Show the user how few engineers the alternative must need before it saves money.
Then ask whether they can run it on fewer.
This puts the staffing question to the user instead of asking them to trust a table.

```text
break-even FTE = (monthly spend the alternative replaces - monthly infrastructure - one-off cost / 36) / monthly engineer cost
```

- **Spend the alternative replaces** comes from their bill in step 1.
  Count only the products the build or self-host would replace.
  Use what they pay, including any discount, not list prices.
- **Person profiles are their own decision.**
  Identified events and group analytics appear as separate lines on the bill.
  They pay for person processing: merging anonymous and identified users, and keeping person and group properties up to date.
  This is the most expensive part of an analytics pipeline to run and the hardest part to rebuild, and builds that look cheap usually skip it.
  Run the comparison two ways, for self-hosting and for building, and keep them apart:
  - **With person profiles:** count the events, identified events, and group analytics lines.
    For both options, infrastructure costs more, because this processing runs on every event that comes in; see "Infrastructure".
    For building, use the full build headcount, because the build must merge identities and keep profiles.
    For self-hosting, the headcount does not change, because PostHog's code already does identity merging.
  - **Without person profiles:** count only the events line.
    Say what they give up: per-user funnels and retention, cohorts, and joining anonymous activity to logged-in users.
    Then compare against PostHog with person processing turned off for the events that don't need it, which often closes most of the gap without building anything.
- Do not quote what person processing costs PostHog to run.
  Explain why it is expensive from what it does, not from internal numbers.
- **Infrastructure** is their own estimate, or the default below.
- **One-off cost** is the build or self-host work plus migration, from "One-off build cost" below.
  Spread over 36 months, the build default alone takes up 0.17-0.33 FTE, so leaving it out can flip the verdict.
- **Engineer cost** is their own figure, or the default for their location below.

How to read the result:

- Zero or negative: infrastructure and the spread one-off cost alone cost more than the bill.
  Say plainly that the alternative cannot win on cost, and stop the cost comparison there.
- The user gave their own staffing estimate: compare it with the break-even headcount directly.
  If their estimate is below the break-even headcount, the alternative can win on cost.
  Do not apply the ownership floor or the staffing defaults to their estimate.
- Otherwise, compare the break-even headcount with the staffing defaults.
  Compare the self-host break-even with the self-host column, and the build break-even with the build column:
  - Below the ownership floor in "Staffing": the alternative cannot win on cost in practice.
  - Above the staffing default for their volume: the alternative can win on cost.
  - In between: the answer depends on their team.
    Ask who would own it and how much of their week it would take.

When the alternative can win on cost, say so, then check "Other things to weigh" before the verdict.

Show the working, so the user can change any input and see the result move.

## Defaults for the ledger

Use these only when the user can't give their own numbers.
They are rough planning figures for a production setup, not quotes.

### Staffing

Headcount is the ongoing run-rate after the build, and includes on-call and incident time.
These figures are planning judgements, not benchmarks.
Tell the user that, and use them to check the break-even headcount, not to replace it.

| Events per month | Self-host PostHog (FTE) | Build your own (FTE) |
| ---------------- | ----------------------- | -------------------- |
| 10M              | Ownership floor         | Ownership floor      |
| 100M             | 0.5                     | 1                    |
| 1B               | 1                       | 2                    |
| 10B              | 2 or more               | 4 or more            |

- **Ownership floor.**
  A system people rely on for decisions needs at least two engineers who know it, so one can be away.
  Use 0.2 FTE in total (two engineers at about 10% each) as the lowest default at any volume.
  At 10M events the pipeline itself is small; the floor is the cost, not the volume.
- Between rows, headcount roughly doubles for every 10x in volume.
- Building needs about twice the self-host headcount.
  The team owns everything PostHog's code would otherwise do: capture, queueing, identity merging, the query layer, and exports.
- Treat the self-host figures as a minimum.
  Self-hosting PostHog beyond the hobby deploy is unsupported, so upgrades and incidents have no vendor to call.
- Treat the 10B row as a minimum.
  Teams at that volume often already have a data platform team, which changes the comparison; see "Who the engineers are".

### One-off build cost

The staffing table starts after the system is live.
Add the work to get there:

- **Build your own:** use two engineers for three to six months as the default (6-12 engineer-months).
  That is $125,000 to $250,000 at the US default engineer cost.
  This covers a production pipeline and the first set of queries, not a product analytics UI.
- **Self-host PostHog:** use one engineer for one to two months as the default (1-2 engineer-months).
- Add the migration work listed under "Other things to weigh" to either option.

Price engineer-months at their engineer cost.
The break-even formula spreads the one-off cost over 36 months.
Show it in full when you compare month 1.

### Who the engineers are

The headcount above assumes engineers who have already run these in production:

- ClickHouse, or another real-time analytics database such as Druid or Pinot: schema and sorting-key design, merges and mutations, upgrades checked against existing queries, backups that have been restored at least once, and capacity planning.
- Kafka, or an equivalent durable queue: partitioning, consumer lag, retention, and replaying after an outage.

If the team doesn't have that experience, say so.
Add hiring or ramp-up time, and expect the first year to need more than the table shows.
If they already run ClickHouse and Kafka for something else, the extra headcount can be lower; that is one of the "right call" criteria.

### Engineer cost

Ask the user what one engineer costs them per year, all in, and where the engineers are based.
Use their number when they give one.

All in means everything the company pays for the engineer, not only salary:

- Salary, bonus, and equity.
- Employer payroll taxes and social contributions, such as US FICA, UK employer National Insurance, or social security in much of Europe.
- Health insurance, pension or retirement contributions, and other benefits.
- Equipment, software, office or remote costs, recruiting fees, and a share of management time.

All in is often 1.2-1.5x base salary, and higher where employer contributions are high.
For contractors, use the full rate they pay, including any agency fee.

If they don't know, use the default for where the engineers are based.
These are rough planning judgements for a senior infrastructure engineer, not salary data:

| Where the engineers are based | All in per year (USD) |
| ----------------------------- | --------------------- |
| United States                 | $250,000              |
| Canada, UK, Australia         | $150,000 - $200,000   |
| Western and Northern Europe   | $130,000 - $180,000   |
| Eastern Europe, Latin America | $85,000 - $130,000    |
| India, Southeast Asia         | $40,000 - $80,000     |

- Use the middle of the range, and show the result at both ends if that changes the verdict.
- If the location is not in the table, use the closest match and say so.
- If they would hire, use the cost where they would hire, not where the current team is.
- Label the figure as a default and ask them to replace it with their own.

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
- **These figures assume anonymous events, with no person processing.**
  This applies to self-hosting and building.
  When the comparison includes person profiles, say that infrastructure costs more than the default.
  List the extra as a cost the comparison could not put a number on, unless the user gives their own estimate.
  Do not quote a multiplier.

## Other things to weigh

These change the verdict and are easy to miss:

- **Migration cost.**
  Count the one-off work: re-instrumenting or redirecting SDKs, rebuilding the dashboards and insights people use, backfilling history, and running both systems side by side until the numbers match.
- **Who asks for features next.**
  Once the pipeline exists, other teams will ask for funnels, retention, cohorts, exports, and access control.
  Each one adds to the headcount.
- **People leaving.**
  Ask what happens when the engineer who built it leaves.
- **What the engineers would otherwise build.**
  The engineer cost default is what the team pays, not what the team loses.
  Ask what those engineers would ship instead.
  If no one is free and they would hire, add hiring time.
  If the team has spare capacity, the real cost is lower than the default; say that too.

### If they already run a warehouse and BI tool

Many teams that ask about building mean this: send events to a warehouse they already run, such as Snowflake or BigQuery, and query them with their BI tool.
Treat it as its own option, because the staffing table does not fit it.

- The extra headcount is much lower than the table, because the warehouse, the pipelines, and the on-call rotation already exist.
  Ask for their own estimate instead of using the staffing defaults.
- It replaces event storage and SQL over events.
  It does not replace funnels, retention, cohorts, identity merging, session replay, feature flags, or experiments.
  Ask which of those the team uses today; each one either stays on the PostHog bill or has to be rebuilt.
- Add the warehouse compute for event-level queries to the infrastructure line.
  Check the provider's pricing page; do not quote it from memory.
- If the team only needs SQL over events, this is often the right call.
  Say so.

## Rules

- Use the public pages, the user's own billing data, and the defaults in this file.
  Label each default as a default and replace it with the user's number when they give one.
- Do not estimate PostHog's infrastructure costs, margins, or internal numbers.
- Separate measured numbers (their billing data) from estimates (their ledger inputs and the defaults).
- Lead with the break-even headcount, which rests on their bill, before any staffing default.
- Say where the numbers favor building, self-hosting, or the warehouse option, including when the result is close.
- If billing tools are unavailable, still read the pages and build the ledger from the volumes the user gives you,
  and say the numbers are theirs, not measured.
