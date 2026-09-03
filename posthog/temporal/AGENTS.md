# Working in `posthog/temporal/`

Pointers, not content. Read the linked docs before changing code or tests in this tree.

## Background on what lives here

- [Temporal at PostHog](./README.md) — concepts, workflows, activities, the conventions we use, common pitfalls, links to the upstream Temporal SDK docs.

## Logging

Never pass structured fields as keyword arguments to `activity.logger` or `workflow.logger`.
Both are stdlib `logging.LoggerAdapter` instances, which forward keyword arguments to `Logger._log()`.
That method accepts only `exc_info`, `stack_info`, `stacklevel` and `extra`, so any other field raises `TypeError`.

- **In an activity, log through the module's structlog logger.** It takes keyword fields directly, and `merge_temporal_context` is registered as a global processor, so the activity id, workflow id and attempt are still attached. See [Logging](./README.md#logging).
- **In a workflow, keep `workflow.logger` and pass fields via `extra={...}`.** Do not switch a workflow to structlog: `workflow.logger` suppresses duplicate logs during replay, and a structlog logger re-logs every replayed line.

`LoggerAdapter.log` checks `isEnabledFor(level)` before it reads the keyword arguments, so a bad `info` call is inert at the default test level of WARNING and fails only in production, which runs at INFO.
In a workflow the crash is a workflow _task_ failure, which Temporal retries forever, so the run wedges instead of failing and reports no error status.
Tests that exercise a workflow end to end should pin `temporalio.activity` and `temporalio.workflow` to INFO, and set an `execution_timeout` so a wedged run fails rather than hangs.

The semgrep rule `temporal-logger-no-keyword-fields` blocks this at review time.

## Writing or modifying tests in this tree

- [Testing patterns](./README.md#testing-patterns) — when to use real Worker vs `ActivityEnvironment` vs no harness, why some files need `@pytest.mark.django_db(transaction=True)`, the module-scoped Worker pattern that avoids booting the temporal-test-server per test, the `connection.connect()` monkeypatch escape hatch, and the parametrize-don't-copy-paste rule.

## Subtree-specific docs (read when working in that area)

- [`data_imports/`](../../products/warehouse_sources/backend/temporal/data_imports/README.md) — data warehouse import pipelines (moved to the warehouse_sources product).
- [`data_modeling/`](./data_modeling/AGENTS.md) — v1 frozen / v2 active split.
- [`signals emission`](../../products/signals/backend/emission/AGENTS.md) — signal emission for data-imports events (moved to the signals product).
- [`sync_person_distinct_ids/`](./sync_person_distinct_ids/README.md), [`experiments/`](./experiments/README.md), [`weekly_digest/`](./weekly_digest/README.md), [`ingestion_acceptance_test/`](./ingestion_acceptance_test/README.md), [`health_checks/`](./health_checks/README.md), [`ai_observability/trace_summarization/`](./ai_observability/trace_summarization/README.md) — each has its own README for context.

## Local eval scripts

- [`ai/slack_app/eval_slack_repo_selection.py`](./ai/slack_app/eval_slack_repo_selection.py) — exercises the Slack `@PostHog` repo-selection cascade (cascade → Haiku gate → discovery agent) against a real team with a connected GitHub integration. Pass/fail summary, no Slack needed. Run as a file (`python posthog/temporal/ai/slack_app/eval_slack_repo_selection.py --list-cases`), not via `python -m` — the latter would force `ai/__init__.py` to load workflows before `django.setup()`. Lives here, not under `management/commands/`, because the import graph it needs (`products/slack_app` + `products/tasks`) is only reachable from `posthog/`.

## Checking the Slack repo discovery agent

Quick sanity checks that `discover_posthog_code_repository_via_agent_activity` is working after a deploy:

- **Temporal UI.** Filter `posthog-code-slack-mention-processing` runs. Healthy: `discover_posthog_code_repository_via_agent_activity` followed by `create_posthog_code_task_for_repo_activity`. Picker-fallback (`post_posthog_code_repo_picker_activity` after the agent) is fine occasionally, alarming if dominant.
- **Slack smoke test.** In a channel with the app and >1 connected repo, `@PostHog Desktop` a message that doesn't name a repo (e.g. "investigate the failing checkout test"). A 🔍 reaction within ~10–60s means the agent ran; the task starting on a real repo means it picked one. A picker on a clear request = something's off.

## Running tests locally

- Activities and most workflows can be tested without spinning up the dev stack: `pytest posthog/temporal/path/to/your_test.py`. Some require the temporal docker service — see the [Local development](./README.md#local-development) section of the main README.
- Batch-export destination tests have extra setup (real BigQuery / Redshift / Databricks credentials). See [`products/batch_exports/backend/tests/temporal/README.md`](../../products/batch_exports/backend/tests/temporal/README.md).
