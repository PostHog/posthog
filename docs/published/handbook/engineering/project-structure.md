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
├── common           # Shared code: PostHog SQL parser, HogVM, shared UI packages
├── tools            # Developer/CI tooling (hogli framework, hogli-commands, openapi-codegen, ...)
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
├── nodejs           # Node.js service for event ingestion and plugins
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
- `src/toolbar` – Code for the [PostHog Toolbar](https://posthog.com/docs/user-guides/toolbar)

The app-level terminal lives in `src/scenes/terminal`.
SQL insights appear as editable `.sql` files; their full JSON remains editable under `/posthog/api/insight`.
Saving SQL preserves the insight's other query options, and JSON saves send only changed fields through the existing APIs.
`run report.sql` executes a SQL file in the current project and prints a Markdown table; `--json`, `--csv`, and `--tsv` select export formats.
CSV and TSV exports escape text that spreadsheets could interpret as formulas.
Use `--json` to inspect result metadata, including `hasMore`, and `/tmp` for export files.
The interactive Bash shell completes `ph` command names, aliases, connected tools, and argument names with Tab.
The terminal follows the current resource's folder while its prompt is empty.
Running commands, editors, and partially typed input prevent a folder change.

The app-level terminal lives in `src/scenes/terminal` and opens with Ctrl+backtick when enabled.
Pi installs on first use from a verified, commit-pinned archive in [PostHog/terminal-assets](https://github.com/PostHog/terminal-assets).
It calls PostHog AI through the signed-in browser session and defaults to Claude Opus 5.
Use `/model` in pi to choose Opus 5, Sonnet 5, Sonnet 4.6, or Haiku 4.5.
The terminal endpoint requires session authentication, project access, the terminal feature flag, and available AI credits.
Gateway credentials stay on the server; configure `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY` for the Go gateway.
The gateway must configure the credential's team as a relay and `posthog_ai` as a billable product so generations count toward the customer's AI credits.
Run one pi session per terminal. The VM has no general network bridge, so external login and package downloads remain unavailable.

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

### `nodejs`

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

- `hogql_parser` – PostHog SQL parser (C++)
- `hogvm` – Hog virtual machine
- `tailwind` – Shared Tailwind configuration

### `tools`

Developer and CI tooling, not imported by runtime code:

- `hogli` – Developer CLI framework (PyPI-publishable)
- `hogli-commands` – PostHog-specific hogli commands
- `openapi-codegen` – OpenAPI client/spec generation
- (and others — see `tools/`)

### `ee`

Enterprise edition licensed features. This directory has a [separate license](https://github.com/PostHog/posthog/blob/master/ee/LICENSE) - not MIT. For 100% FOSS code, see [PostHog/posthog-foss](https://github.com/PostHog/posthog-foss).

### `playwright`

End-to-end tests using [Playwright](https://playwright.dev/). Tests live in the `e2e/` subdirectory.

### `livestream`

Golang service powering the live events feed in the **Activity** tab.
