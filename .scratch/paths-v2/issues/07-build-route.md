# Build route

Type: grilling
Status: open
Blocked by: 04, 06

## Question

Revive [PR #29364](https://github.com/PostHog/posthog/pull/29364) or re-implement — and in what increments?

Decide:

- **Rebase vs fresh**: the branch predates the paths-runner move to `products/product_analytics/` and a year of schema/scene churn (divergence facts in [Draft-work autopsy](01-draft-work-autopsy.md)). Carry the diff forward, or treat it as a reference implementation and rebuild in place?
- **Where v2 lives**: `products/product_analytics/backend/hogql_queries/paths_v2/` next to v1, plus the shared layer from [Funnel-reuse strategy](04-funnel-reuse-strategy.md).
- **Increment plan**: slice into shallow stacked PRs (schema+runner, viz, editor filters, interop) per repo CI guidance — name the slices and their order.
- **Test strategy**: port the draft's 732-line runner test file or restart; add the funnel-equality fixtures decided in [Funnel-reuse strategy](04-funnel-reuse-strategy.md).

Output: an ordered PR/work-package list a build session can pick up directly.
