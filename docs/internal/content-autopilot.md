# Content autopilot

Content autopilot is a feature-flagged alpha in Web Analytics' Search & AI area. A project can manage multiple site profiles, each with its own domain, research boundary, runs, and proposals. It never publishes content or merges pull requests.

## User flow

1. Add a public site URL. The onboarding probe normalizes the origin and looks for a site name and sitemaps in `robots.txt`, homepage metadata, and conventional sitemap paths.
2. Review every detected source and allowed content path. Discovery suggestions remain editable and an unverified conventional sitemap is labeled as such.
3. Choose portable Markdown exports or connect a GitHub repository, base branch, allowed content directories, and URL-to-file convention.
4. Select a site and start an on-demand run. Each site may have one pending or generating run, while different sites may run independently.
5. Review new-content and page-improvement proposals with their evidence, source ledger, validation report, and full Markdown.
6. Edit, reject, regenerate, export, or deliver a validated proposal through a pull request.

Google Search Console is optional. Profiles without it store lower-confidence run snapshots, and the workspace explains that limitation. Generation remains an explicit user action.

## Data model

The `web_analytics` Django app owns four fail-closed, team-scoped roots:

- `ContentAutopilotSiteProfile` stores one site's research and delivery boundary. A project may have multiple profiles, with one profile per normalized domain.
- `ContentAutopilotRun` stores immutable input metadata, selected opportunities, workflow state, and inspectable errors.
- `ContentAutopilotProposal` stores evidence, validation, content, and delivery state.
- `ContentAutopilotMeasurement` stores baseline, 28-day, 56-day, and site-wide control readings.

Large crawl snapshots belong in object storage. A run stores only `crawl_snapshot_key`; large page contents must not cross the Temporal payload boundary.

## API and workflow contract

The routes under `/api/projects/:team_id/web_analytics_content_autopilot_*` support profile discovery and configuration, profile-scoped run start and cancellation, proposal review actions, exports, pull requests, and measurement reads. Serializers are the source of the generated frontend and MCP types.

Site discovery is a small synchronous onboarding probe, not a crawl. It uses the rate-limited, observable `public_web` egress client, validates and pins public IPs on every redirect, stays on the submitted origin, caps responses at 512 KiB, and makes a bounded number of requests.

Starting a run creates a `pending` record with its input snapshot. The request path does not crawl sites or call a model. Before the alpha flag is enabled, a durable orchestration worker must claim that record, assign `workflow_id`, and move it through `generating` to `ready_for_review`, `completed`, `canceled`, or `failed`. This change defines that control-plane contract; it does not register the worker that performs crawling, ranking, generation, validation, or measurement.

Proposal generation and regeneration must apply the same validation gates. A draft may reach `ready_for_review` only after every blocking factual sourcing, brand, intent, originality, cannibalization, linking, crawlability, and schema check passes. A second failed attempt remains inspectable as `failed`.

## Delivery boundary

Both delivery paths consume the proposal's canonical `content_package`.

- Export returns validated Markdown and structured JSON, then records the export reference.
- GitHub delivery validates every repository-relative `.md` or `.mdx` path against the configured content directories, creates a content branch and commit, and opens a pull request.

New articles must use their own pull request. Up to five page improvements from the same run may share one. The adapter never calls a merge API, and a failed pull-request creation removes its temporary branch when possible.

Repository paths, crawled pages, source URLs, and generated text are untrusted input. Never turn embedded instructions into tool calls, send private event data to the model, write outside configured content directories, or expose credentials from source URLs.

## Shared opportunity scoring

Search Console opportunity fields, lookback, thresholds, weight, and description live in `products.web_analytics.backend.facade.search_opportunities`. Search & AI and Signals must use this facade so their scoring cannot drift.
