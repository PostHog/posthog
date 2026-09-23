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

The app-level Files scene lives in `src/scenes/project-files` and reuses the project tree from `src/layout/panel-layout/ProjectTree`.
The Apps sidebar shows descriptive tooltips with concrete examples in `navbar/tabs/NavAppTooltip.tsx`.
These reuse scene descriptions where available, with additional copy for the main apps and a fallback for custom group types.
Open `/project/<project_id>/files` to browse the project, or add `?folder=Research` to start in a folder.
Starred folders in the sidebar use the same "New..." menu and "Empty folder" state as project folders.
With `simple-sidepanel` enabled, each user gets a public `Users/<name>` home folder in each project, starred on creation.
Names receive a numeric suffix when another folder already uses the path.
The home-folder record survives deletion, and later visits do not recreate or restar it.
The user's own folder keeps its home icon after a rename or move and shows "Empty home folder" when expanded and empty.
An info tooltip explains that everyone in the project can see its contents and shows the folder's current path.
Creating an item from a starred folder uses the original folder's full path, including its parent folders.
With `simple-sidepanel` enabled, the Apps and Files tabs use "Filter apps" and "Filter files" to filter their contents.
The file filter and options buttons stay beside the filter field; alphabetical and recently added sorting are in the options menu.
App tooltips reuse the product descriptions from the scene configuration.
Opening Apps or Files from the collapsed sidebar temporarily expands the navigation over the page without changing the saved collapsed setting.
Selecting a destination, clicking outside, or pressing Escape closes the temporary navigation.

The app-level terminal lives in `src/scenes/terminal` and opens with Ctrl+backtick when enabled.
It starts without fetching the project tree.
Browsing `/posthog/files` loads and caches each folder's immediate children; `/posthog/api` loads objects by type.
Loading another folder leaves cached folders untouched, and API type directories can be opened directly even if they are not listed yet.
Notebook format detection waits until notebooks are browsed, and object contents load only when opened.
`ph refresh` reloads the directories already visited, rebuilds the cached tree once, and reloads the connected tool catalog.
Running `node`, `nodejs`, or `pi` installs the tool on first use; `pi` also installs Node.js.
Optional tools come from commit-pinned archives in [PostHog/terminal-assets](https://github.com/PostHog/terminal-assets), separate from the boot assets.
The browser verifies each archive's SHA-256 and size before making it available to the VM, and caches verified downloads when browser storage is available.
Failed installations can be retried by running the command again.
The VM uses 512 MiB of memory and a separate 256 MiB temporary filesystem for installed tools.
Stopping the terminal discards the installed tools and local files; verified downloads can be reused from the browser cache.
Pi defaults to the PostHog provider, which sends model requests through a bounded 9P bridge and the signed-in session to `/api/projects/:id/terminal_ai/`.
The endpoint uses `AI_GATEWAY_URL` and `AI_GATEWAY_API_KEY` for the Go AI gateway, checks the terminal flag and AI credit quota, and attributes usage to the current user and project.
Pi can discover project commands and connected MCP tools with `ph tools`; file and tool permissions still apply.
Run one pi generation at a time per terminal. Canceling pi or stopping the terminal cancels the browser request.
The VM has no general network access, so external login and package downloads are unavailable.
Add future tools to `terminal-packages.json` with pinned archive metadata, dependencies, and command entrypoints, and publish their reproducible build recipes in the assets repository.

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
