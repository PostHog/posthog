---
title: Project structure
sidebar: Docs
showTitle: true
---

> **Note:** This page refers to our [main product repository](https://github.com/PostHog/posthog), not our website.

## Directory tree

```text
.
├── bin              # Shell scripts wrapped by hogli, the unified developer CLI
├── common           # Shared code: hogli CLI, PostHog SQL parser, HogVM, shared UI packages
├── ee               # Enterprise platform package features (separate license)
├── frontend         # React/TypeScript frontend application
│   └── src
│       └── layout   # App layout components (navigation, sidebars)
│       └── lib      # Reusable components and utilities
│       └── scenes   # Page-specific components
│       └── queries  # Query builder components
│       └── toolbar  # PostHog Toolbar code
├── livestream       # Golang service for live events API
├── playwright       # End-to-end tests using Playwright
├── plugin-server    # Node.js service for event ingestion and plugins
├── posthog          # Django backend application
│   └── api          # REST API endpoints
│   └── clickhouse   # ClickHouse database interactions
│   └── hogql        # HogQL query language implementation
│   └── models       # Django ORM models
│   └── tasks        # Celery background tasks
├── products         # Product-specific code (vertical slices)
└── rust             # High-performance Rust services

*Selected subdirectories only
```

## Key directories

### `frontend`

The PostHog web application, built with React and TypeScript. Uses [Kea](https://github.com/keajs/kea) for state management.

- `src/lib` – Reusable components and utilities
- `src/scenes` – Page-specific components organized by feature
- `src/queries` – Query builder and data visualization components
- `src/toolbar` – Code for the [PostHog Toolbar](/docs/user-guides/toolbar)

### `posthog`

The Django backend application. Key subdirectories:

- `api` – REST API endpoints and serializers
- `clickhouse` – ClickHouse schema definitions and migrations
- `hogql` – PostHog SQL query language compiler and executor
- `models` – Django ORM models (PostgreSQL)
- `tasks` – Celery background tasks

### `products`

Product-specific code organized as **vertical slices**. Each product folder contains its own backend (Django app), frontend (React), and optionally shared code. This structure allows features to evolve independently.

See the [products README](https://github.com/PostHog/posthog/blob/master/products/README.md) for detailed conventions.

### `plugin-server`

Node.js service responsible for:

- Event ingestion and processing
- Running plugins and data pipelines
- Webhook delivery

### `rust`

High-performance Rust services including:

- `capture` – Event capture endpoint
- `feature-flags` – Feature flag evaluation
- `cymbal` – Error tracking symbolication
- Various workers and utilities

### `common`

Shared code used across the codebase:

- `hogli` – Unified developer CLI for building, testing, and running PostHog
- `hogql_parser` – PostHog SQL parser (C++)
- `hogvm` – Hog virtual machine
- `tailwind` – Shared Tailwind configuration

### `ee`

Enterprise edition licensed features. This directory has a [separate license](https://github.com/PostHog/posthog/blob/master/ee/LICENSE) - not MIT. For 100% FOSS code, see [PostHog/posthog-foss](https://github.com/PostHog/posthog-foss).

### `playwright`

End-to-end tests using [Playwright](https://playwright.dev/). Tests live in the `e2e/` subdirectory.

### `livestream`

Golang service powering the live events feed in the **Activity** tab.
