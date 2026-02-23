# Browser lab testing

## What is Browser lab testing?

Synthetic monitoring —
scripted browser journeys running in headless Chrome on a schedule.
This complements field testing (real-user monitoring)
which PostHog already captures via `$web_vitals` events.

Lab testing catches regressions before users hit them,
provides deterministic baselines without user-mix confounding,
and exposes deeper instrumentation
(JS heap size, DOM node count, dropped frames, long tasks)
via the Chrome DevTools Protocol.

## Lab testing vs field testing

|                 | Field testing (RUM)                   | Lab testing (synthetic)                       |
| --------------- | ------------------------------------- | --------------------------------------------- |
| **Data source** | Real users                            | Headless Chrome                               |
| **Conditions**  | Variable (device, network, geography) | Controlled and repeatable                     |
| **Coverage**    | Organic — whatever users do           | Scripted — explicit journeys                  |
| **Metrics**     | Core Web Vitals                       | Web Vitals + heap + DOM + frames + long tasks |
| **Scheduling**  | Continuous (piggybacks on traffic)    | Interval (cron / Temporal schedule)           |
| **Use case**    | Real-world performance distribution   | Regression detection, baseline tracking       |

## Architecture overview

```text
BrowserLabTest model (starting URL + step primitives)
        │
        ▼
   API: POST /api/projects/:team_id/browser_lab_tests/:id/run
        │
        ▼
   Temporal workflow  ("run-browser-lab-test")
   task queue: browser-lab-testing-task-queue
        │
        ▼
   Playwright activity (headless Chrome in worker pod)
        │
        ▼
   $browser_lab_test_run event → PostHog insights / alerts / dashboards
```

Key pieces:

- **`BrowserLabTest`** —
  stores a starting URL and an ordered list of step primitives as JSON.
  No arbitrary user code.
- **`BrowserLabTestRun`** —
  tracks status (pending → running → completed / failed), result JSON, and timing.
- **Temporal workflow** on `browser-lab-testing-task-queue` —
  orchestrates the run.
  The worker pod runs Playwright against headless Chrome.
- **Event capture** —
  the activity emits `$browser_lab_test_run` events with metrics.
  Standard PostHog insights, alerts, and dashboards work out of the box.

## Step primitives

Test steps are declarative JSON —
no arbitrary JavaScript execution (important for multi-tenant safety).

Each step has a `phase` that controls when metrics are collected:

| Phase     | Purpose                                   | Metrics collected? |
| --------- | ----------------------------------------- | ------------------ |
| `arrange` | Set up the page state before measurement  | No                 |
| `act`     | The interaction you're actually measuring | Yes                |
| `assert`  | Verify the outcome after measurement      | No                 |

This matters because setup noise pollutes the signal.
For example, if you care about dropped frames when clicking a button to navigate from page X to page Y,
you don't want loading page X (arrange) or checking text on page Y (assert) included in the measurement.
Only the click and resulting navigation (act) should contribute metrics.

A test's steps JSON looks like:

```json
[
  { "phase": "arrange", "action": "navigate", "url": "https://app.example.com/dashboard" },
  { "phase": "arrange", "action": "waitForSelector", "selector": "#main-content" },
  { "phase": "act", "action": "click", "selector": "#deploy-button" },
  { "phase": "act", "action": "waitForNavigation" },
  { "phase": "assert", "action": "assertText", "selector": "#status", "text": "Deployed" }
]
```

The Playwright activity starts DevTools Protocol instrumentation (performance observer, heap sampling, frame tracking)
at the first `act` step and stops it after the last `act` step.
Metrics on the emitted event reflect only the `act` window.

### Primitives

| Primitive           | Description                     |
| ------------------- | ------------------------------- |
| `navigate`          | Go to a URL                     |
| `click`             | Click an element by selector    |
| `type`              | Type text into an input         |
| `waitForSelector`   | Wait for an element to appear   |
| `waitForNavigation` | Wait for a page navigation      |
| `screenshot`        | Capture a screenshot            |
| `assertText`        | Assert text content on the page |
| `scroll`            | Scroll the page or an element   |

## Components needed to ship

| Component                                     | Status          | Notes                                                                    |
| --------------------------------------------- | --------------- | ------------------------------------------------------------------------ |
| `BrowserLabTest` / `BrowserLabTestRun` models | Done            | `backend/models.py`                                                      |
| Temporal workflow stub                        | Done            | `backend/temporal/run_browser_lab_test/workflow.py`                      |
| API (CRUD + run trigger)                      | Done            | `backend/api.py`, routes in `posthog/api/__init__.py`                    |
| Task queue config                             | Done            | `posthog/settings/temporal.py`                                           |
| Worker registration                           | Done            | `start_temporal_worker.py`                                               |
| Workflow test                                 | Done            | `tests/test_workflow.py`                                                 |
| Playwright activity implementation            | Done            | `activities.py` — two sync activities: `fetch` (DB) + `run` (Playwright) |
| Feature flag gate                             | TODO            |                                                                          |
| Product manifest + sidebar entry              | TODO            |                                                                          |
| Config UI (create / edit test)                | TODO            | Frontend scene                                                           |
| Schedule config UI                            | TODO            | Cron / interval picker                                                   |
| Schedule backend                              | TODO            | Temporal schedules via `posthog/temporal/common/schedule.py`             |
| Run status UI                                 | TODO            | List runs, show results                                                  |
| Playwright activity — step execution          | Done            | `navigate` supported; other primitives are TODO                          |
| Event capture from activity                   | TODO            | `posthoganalytics.capture()` for `$browser_lab_test_run`                 |
| Insights / alerts                             | No special code | Events feed the standard system                                          |
| Charts repo worker deploy                     | TODO            | Playwright + Chrome in worker image                                      |

## Events emitted

### `$browser_lab_test_run`

Emitted once per completed run.
Performance metrics cover only the `act` phase of the test.
Properties:

| Property                  | Type      | Description                                                   |
| ------------------------- | --------- | ------------------------------------------------------------- |
| `browser_lab_test_id`     | `uuid`    | Test definition ID                                            |
| `browser_lab_test_run_id` | `uuid`    | Run ID                                                        |
| `browser_lab_test_name`   | `string`  | Human-readable test name                                      |
| `success`                 | `boolean` | Whether the run passed                                        |
| `error`                   | `string?` | Error message if failed                                       |
| `total_duration_ms`       | `number`  | Full run duration (arrange + act + assert). Used for billing. |
| `duration_ms`             | `number`  | Act-phase duration                                            |
| `lcp_ms`                  | `number`  | Largest Contentful Paint                                      |
| `fcp_ms`                  | `number`  | First Contentful Paint                                        |
| `cls`                     | `number`  | Cumulative Layout Shift                                       |
| `inp_ms`                  | `number`  | Interaction to Next Paint                                     |
| `js_heap_used_bytes`      | `number`  | JS heap size                                                  |
| `dom_node_count`          | `number`  | DOM node count                                                |
| `dropped_frames`          | `number`  | Dropped animation frames                                      |
| `long_task_count`         | `number`  | Tasks > 50 ms                                                 |

## Open questions / future work

- **Record-and-replay from toolbar** — let users record a journey in their app and convert it to step primitives
- **Visual regression** — screenshot diffing between runs
- **Network throttling** — simulate slow connections (3G, slow 4G)
- **Geo distribution** — run from multiple regions
- **Auth handling** — cookie injection or login step primitives for authenticated journeys
- **Parallel tests** — fan out multiple tests in a single schedule tick
- **Cost control / billing** — metering per-run, team quotas
