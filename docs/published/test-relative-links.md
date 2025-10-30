---
title: Test Relative Links (PoC)
---

# Test Document for Relative Link Rewriting

This document tests the gatsby-remark-rewrite-relative-links plugin.

## Relative Links (should be rewritten)

### Same directory
- Link to [Safe Django Migrations](./safe-django-migrations.md)
- Link to [Stack documentation](./stack.md)
- Link to [Development process](./development-process.md)

### Subdirectory
- Link to [ClickHouse data storage](./clickhouse/data-storage.mdx)
- Link to [Backend coding conventions](./conventions/backend-coding.md)
- Link to [AI architecture](./ai/architecture.md)
- Link to [Database schema changes](./databases/schema-changes.md)

### With anchors
- Link to [ClickHouse storage with anchor](./clickhouse/data-storage.mdx#partition-by)
- Link to [AI products with anchor](./ai/products.md#posthog-ai)

### README/index normalization
- Link to [ClickHouse index](./clickhouse/index.mdx)
- Link to [ClickHouse schema index](./clickhouse/schema/index.mdx)

## Absolute Paths (should remain unchanged)

### Links to other posthog.com sections
- User docs: [PostHog AI documentation](/docs/posthog-ai)
- Team page: [PostHog AI team](/teams/posthog-ai)
- Blog post: [ClickHouse materialized columns](/blog/clickhouse-materialized-columns)

### Links to user-facing docs
- [User guides - Retention](/docs/user-guides/retention)
- [Self-host on AWS](/docs/self-host/deploy/aws)

## External Links (should remain unchanged)

- [PostHog GitHub](https://github.com/PostHog/posthog)
- [ClickHouse docs](https://clickhouse.com/docs/)

## Non-markdown Links (should remain unchanged)

- Image: ![Diagram](../images/architecture-diagram.png)
- PDF: [Technical spec](../pdfs/spec.pdf)

## Edge Cases

### Anchor-only links
- [Jump to section](#relative-links-should-be-rewritten)

### Query parameters
- [Link with query](./stack.md?section=backend)

### Complex relative paths
- [Two levels up](../../README.md)
