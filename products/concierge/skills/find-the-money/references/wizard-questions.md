# Wizard questions

The wizard asks these questions before invoking the skill. If you're invoking the
skill manually, ask them in the same order. Skip a question only if it's already
unambiguously answered by the project's data (e.g. only one revenue event exists).

## Required

### 1. Business shape

> How do you make money?

- **Subscription** — recurring plans (SaaS, streaming, memberships)
- **One-time** — ecommerce, app purchases, course sales
- **Usage-based** — pay-per-use, metered billing
- **Ads** — revenue from advertisers, not users
- **Mixed** — combination of the above

Why it matters: changes which analyses apply. Subscription unlocks tier-squeeze and
dormant-payer analyses; one-time unlocks repeat-purchase analyses; ads invert the
"who's the buyer" question.

### 2. Buyer unit

> Is your buyer a person or an organization?

- **Person** — individual signs up and pays for themselves (consumer SaaS, B2C)
- **Organization / team** — one account pays for many users (B2B SaaS)
- **Both** — self-serve + sales-assist hybrid

Why it matters: B2B revenue analyses must use group analytics (`group_0` /
organization group type), not person properties. Otherwise the skill double-counts
seats as separate buyers.

### 3. Focus area — pick one (or "surprise me")

> What are you trying to find?

- **Grow new revenue** — acquisition leaks, channel ROI, conversion choke points
- **Expand existing** — upsell/cross-sell, tier mismatches, feature → upgrade signals
- **Save at-risk revenue** — churn risk, dormant payers, declining engagement
- **Surprise me** — run the top 2 analyses from each focus area, shallower each

### 4. Time window

> How far back should we look?

Default 90 days. Shorter (30d) for fast-moving products; longer (180d–365d) for
slow sales cycles or seasonal businesses.

### 5. Exclusions

> Anything to exclude from the analysis?

- Internal employee emails (default: filter on company domain if detected)
- Test organizations / test users
- Free-tier traffic, if it would dominate the dataset and obscure paying behavior

## Optional but high-value

### 6. Revenue signal hints

> What's your revenue event called, and where's the amount stored?

Autodetect first — look for events named `purchase`, `subscription_created`,
`payment_succeeded`, `order_completed`, `checkout_completed`, and properties named
`$revenue`, `revenue`, `amount`, `price`, `total`. If multiple candidates exist,
ask which one represents booked revenue (vs. previews, refunds, etc.).

### 7. Plan / tier property

> Where do you track which plan a user is on?

Autodetect common person-property names: `plan`, `subscription_tier`, `pricing_plan`,
`tier`, `subscription_status`. If found, list distinct values and confirm.

### 8. Group properties (B2B only)

> Do organizations have properties like `industry`, `arr`, `seats`, or `mrr`?

Asking unlocks segment ROI by org property — usually the highest-signal cut for B2B.

### 9. Prior attempts

> What have you already tried to grow revenue that didn't work?

The skill uses this to deprioritize findings that recommend the same thing. Saves
the user reading recommendations they've already rejected.

### 10. Depth

> Quick scan or deep dive?

- **Quick scan** — ~5 analyses, single short report (~10 minutes of reading)
- **Deep dive** — ~12 analyses, longer report with more cross-cuts

## Branching notes

- If business shape = **ads**, swap the "expand existing" focus for an advertiser-ROI
  analysis (revenue per impression by advertiser, fill-rate analysis).
- If buyer unit = **organization** and no group types are defined, warn that the
  skill will fall back to person-based analyses and may overcount.
- If the user picks **surprise me** but explicitly lists exclusions that gut a focus
  area (e.g. "exclude all free users" + grow-new), drop that focus area and tell
  them why.
