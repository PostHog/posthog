# Funnel-reuse strategy

Type: grilling
Status: open
Blocked by: 02, 03

## Question

At which layer do paths v2 and funnels share code?

Options to weigh (facts from [Funnels machinery map](02-funnels-machinery-map.md)):

1. **Build paths on the funnel engine** — compile a paths query into funnel-UDF invocations (or extend the UDF to emit step sequences). Numbers match funnels by construction; risk: UDF complexity, N-way steps explosion.
2. **Share the semantic core** — reuse funnel event query, entity→expr, window + actor-resolution utilities, but keep paths' own array SQL on top. Equality holds only if the shared pieces carry all the semantics from [Counting semantics](03-counting-semantics.md).
3. **Independent SQL + provable converter** — keep the draft's pipeline; ship a paths→funnel query converter whose output is tested (same fixtures, asserted equal counts) rather than shared-by-construction.

Also decide:

- The **path→funnel** affordance: what funnel query the "view as funnel" action emits for a selected edge/segment, and how equality is guaranteed (shared code vs cross-checked tests).
- The **funnel→paths** direction: keep/port v1's `FunnelPathsFilter` (paths after/before/between funnel steps) into v2, now or later.
- Where the code lives: funnels sit in `posthog/hogql_queries/insights/funnels/`, v1 paths in `products/product_analytics/` — pick a home that keeps the shared layer importable by both.
