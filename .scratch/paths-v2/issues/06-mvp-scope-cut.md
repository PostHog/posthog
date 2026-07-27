# MVP scope cut

Type: grilling
Status: open
Blocked by: 03, 05

## Question

Which capabilities ship in the first flagged release of paths v2, and which defer?

Walk the candidate list (draft todos + tracking-issue wishlist), in/out one by one:

- Start/end point trimming (draft has partial support, unchecked in PR todos).
- Arbitrary event selection like lifecycle ([#17161](https://github.com/PostHog/posthog/issues/17161)) vs v1's `$pageview`/`$screen`/all buckets.
- Property-based step expansion ([#11086](https://github.com/PostHog/posthog/issues/11086)).
- Aggregation by group/session ("event journeys", [#33488](https://github.com/PostHog/posthog/issues/33488)).
- Persons modal / actors query (see [Actors drill-down consistency](08-actors-drilldown-consistency.md)).
- Path cleaning application (v1 parity) and `collapseEvents`.
- Query summary (`PathsV2Summary`), context menu ("view as funnel"), funnel→paths.
- Exclusions, wildcards/aliases, intermediate-step orders (draft marks these "later").

Output: a two-list cut (MVP / later) the [Build route](07-build-route.md) can be sized against.
