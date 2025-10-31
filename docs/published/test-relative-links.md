---
title: Test Relative Links (PoC)
---

# Test Document for Relative Link Rewriting

This document tests the simplified gatsby-remark-rewrite-relative-links plugin.

## Plugin Behavior

The plugin does two things:
1. **Strips `.md`/`.mdx` extensions** from relative links (keeps paths relative!)
2. **Normalizes posthog.com URLs** to relative paths (better client-side routing)

## Relative Links (extension should be stripped)

### Same directory
- Link to [Safe Django Migrations](./safe-django-migrations.md) - should become `./safe-django-migrations`
- Link to [Stack documentation](./stack.md) - should become `./stack`
- Link to [Development process](./development-process.md) - should become `./development-process`

### Subdirectory
- Link to [ClickHouse data storage](./clickhouse/data-storage.mdx) - should become `./clickhouse/data-storage`
- Link to [Backend coding conventions](./conventions/backend-coding.md) - should become `./conventions/backend-coding`
- Link to [AI architecture](./ai/architecture.md) - should become `./ai/architecture`
- Link to [Database schema changes](./databases/schema-changes.md) - should become `./databases/schema-changes`

### With anchors (should preserve)
- Link to [ClickHouse storage with anchor](./clickhouse/data-storage.mdx#partition-by) - should become `./clickhouse/data-storage#partition-by`
- Link to [AI products with anchor](./ai/products.md#posthog-ai) - should become `./ai/products#posthog-ai`

### With query parameters (should preserve)
- [Link with query](./stack.md?section=backend) - should become `./stack?section=backend`

### README/index files
- Link to [ClickHouse index](./clickhouse/index.mdx) - should become `./clickhouse/index`
- Link to [ClickHouse schema index](./clickhouse/schema/index.mdx) - should become `./clickhouse/schema/index`

## posthog.com URLs (should be normalized)

These links use full URLs in source (good for GitHub) but should be normalized to relative paths (good for web):

- [PostHog AI docs](https://posthog.com/docs/posthog-ai) - should become `/docs/posthog-ai`
- [PostHog AI team](https://posthog.com/teams/posthog-ai) - should become `/teams/posthog-ai`
- [Blog post](https://posthog.com/blog/clickhouse-materialized-columns) - should become `/blog/clickhouse-materialized-columns`
- [With anchor](https://posthog.com/docs/sql#queries) - should become `/docs/sql#queries`
- [With query param](https://posthog.com/blog/post?utm_source=docs) - should become `/blog/post?utm_source=docs`

## Absolute Paths (should remain unchanged)

- User docs: [PostHog AI documentation](/docs/posthog-ai) - stays `/docs/posthog-ai`
- Team page: [PostHog AI team](/teams/posthog-ai) - stays `/teams/posthog-ai`
- Blog post: [ClickHouse materialized columns](/blog/clickhouse-materialized-columns) - stays `/blog/clickhouse-materialized-columns`
- User guides: [Retention](/docs/user-guides/retention) - stays `/docs/user-guides/retention`
- Self-host: [AWS deployment](/docs/self-host/deploy/aws) - stays `/docs/self-host/deploy/aws`

## External Links (should remain unchanged)

- [PostHog GitHub](https://github.com/PostHog/posthog) - stays as-is
- [ClickHouse docs](https://clickhouse.com/docs/) - stays as-is

## Non-markdown Links (should remain unchanged)

- Image: ![Diagram](../images/architecture-diagram.png) - stays as-is
- PDF: [Technical spec](../pdfs/spec.pdf) - stays as-is

## Edge Cases

### Anchor-only links
- [Jump to section](#relative-links-extension-should-be-stripped) - stays as-is

### Complex relative paths
- [Two levels up](../../README.md) - should become `../../README`

## Expected Results

When viewing this page on the Vercel preview at `/handbook/engineering/test-relative-links`:

1. **Relative links** should resolve correctly (no 404s) because `.md` was stripped but path stayed relative
2. **posthog.com URLs** should navigate with client-side routing (no page reload)
3. **Absolute paths** should work as-is
4. **External links** should work as-is
