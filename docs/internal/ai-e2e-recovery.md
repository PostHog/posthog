# AI browser recovery runner

The [AI E2E architecture](../../products/posthog_ai/frontend/e2e/architecture.md) describes the real service boundaries,
replayed model responses, fault controls, and evidence collected by the recovery suite.

Run from the repository root through `.codex/with-flox hogli test:e2e:ai`. `--attach` reuses infrastructure while still
creating a fresh application database. The Postgres role must have database creation privileges. The runner drops only
its own application database; it does not dispatch another developer's queued tasks. Configure auxiliary stores and
Temporal before attaching. The launcher starts its own Django, MCP, agent-proxy, dispatcher, and tasks worker.

The committed [flag manifest](../../products/posthog_ai/frontend/e2e/flags.json) selects the proxy and durable dispatcher
path. Browser, backend, and MCP consumers derive their values from that file. Add an explicit entry when introducing a
flag on the exercised path. CI does not contact production feature-flag evaluation or import production targeting data.

In the existing E2E workflow, the AI job runs in parallel with regular Playwright. One worker runs the six Claude/Codex
recovery cases against one stack. Normal AI runs have a 30-minute job timeout and retain the existing default of one retry.
Manual `ai_repeat_each=10` selects the 90-minute stability run and requires zero retries. Existing path filters, draft
behavior, and the required Playwright check remain unchanged. Older checkouts without the AI tooling still skip its steps.

Artifacts include browser traces, proxy and dispatcher logs, effective flags, observed backend flag decisions, image
provenance, per-stage timings, and peak memory. Ten zero-retry repetitions on the actual CI runner establish stability;
cold and warm normal runs establish whether the suite fits its timeout. Historical Django-stream results do not establish
stability or runtime for the proxy profile.

The production `run_task_workflow_dispatcher` command accepts `--metrics-port` and `--health-directory`. Defaults remain
port `8001` and `/tmp`, producing `dispatcher-ready` and `dispatcher-heartbeat`. The E2E bootstrap uses an allocated metrics
port and its artifact directory so it does not collide with another dispatcher. Readiness files are removed on shutdown.
