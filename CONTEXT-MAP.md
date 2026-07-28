# Context Map

Per-context domain glossaries for this monorepo.
Each `CONTEXT.md` is a glossary only: canonical terms, tight definitions, words to avoid.

## Contexts

- [Product analytics](./products/product_analytics/CONTEXT.md) — insight queries and visualizations over captured events (currently: paths v2 terms)

## Relationships

- **Product analytics → funnels core**: paths v2 imports funnel primitives (entity expressions, window arithmetic, actor resolution) and emits funnel queries that must reproduce path numbers exactly (see "edge contract" in the product analytics glossary)
