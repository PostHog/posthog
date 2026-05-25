# Working in `posthog/temporal/`

Pointers, not content. Read the linked docs before changing code or tests in this tree.

## Background on what lives here

- [Temporal at PostHog](./README.md) — concepts, workflows, activities, the conventions we use, common pitfalls, links to the upstream Temporal SDK docs.

## Writing or modifying tests in this tree

- [Testing patterns](./README.md#testing-patterns) — when to use real Worker vs `ActivityEnvironment` vs no harness, why some files need `@pytest.mark.django_db(transaction=True)`, the module-scoped Worker pattern that avoids booting the temporal-test-server per test, the `connection.connect()` monkeypatch escape hatch, and the parametrize-don't-copy-paste rule.

## Subtree-specific docs (read when working in that area)

- [`data_imports/`](./data_imports/README.md) — data warehouse import pipelines.
- [`data_modeling/`](./data_modeling/AGENTS.md) — v1 frozen / v2 active split.
- [`data_imports/signals/`](./data_imports/signals/AGENTS.md) — signal emission for data-imports events.
- [`sync_person_distinct_ids/`](./sync_person_distinct_ids/README.md), [`experiments/`](./experiments/README.md), [`weekly_digest/`](./weekly_digest/README.md), [`ingestion_acceptance_test/`](./ingestion_acceptance_test/README.md), [`health_checks/`](./health_checks/README.md), [`llm_analytics/trace_summarization/`](./llm_analytics/trace_summarization/README.md) — each has its own README for context.

## Local eval scripts

- [`ai/eval_slack_repo_selection.py`](./ai/eval_slack_repo_selection.py) — exercises the Slack `@PostHog` repo-selection cascade (cascade → Haiku gate → discovery agent) against a real team with a connected GitHub integration. Pass/fail summary, no Slack needed. Run as a file (`python posthog/temporal/ai/eval_slack_repo_selection.py --list-cases`), not via `python -m` — the latter would force `ai/__init__.py` to load workflows before `django.setup()`. Lives here, not under `management/commands/`, because the import graph it needs (`products/slack_app` + `products/tasks`) is only reachable from `posthog/`.

## Running tests locally

- Activities and most workflows can be tested without spinning up the dev stack: `pytest posthog/temporal/path/to/your_test.py`. Some require the temporal docker service — see the [Local development](./README.md#local-development) section of the main README.
- Batch-export destination tests have extra setup (real BigQuery / Redshift / Databricks credentials). See [`products/batch_exports/backend/tests/temporal/README.md`](../../products/batch_exports/backend/tests/temporal/README.md).
