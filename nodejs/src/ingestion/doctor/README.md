# Pipeline Doctor

Convention-checking agents for the PostHog ingestion pipeline.
The agents use the doc-test chapters in `pipelines/docs/` as their source of truth
and review code for adherence to framework patterns.

## Agents

| Agent                         | Concern                                | Key chapters     |
| ----------------------------- | -------------------------------------- | ---------------- |
| `pipeline-step-doctor`        | Step structure, types, factory pattern | 01, 13           |
| `pipeline-result-doctor`      | Results, side effects, warnings        | 07, 08, 09       |
| `pipeline-composition-doctor` | Builder chain, concurrency, branching  | 02-06, 10-12, 13 |
| `pipeline-testing-doctor`     | Test patterns, helpers, assertions     | All 13 chapters  |

## Invocation

Each agent lives in `.claude/agents/ingestion/` and Claude auto-selects the right one based on your request:

```text
> Review my new step for type safety         -> pipeline-step-doctor
> Check my result handling                   -> pipeline-result-doctor
> Help me compose a subpipeline              -> pipeline-composition-doctor
> Review tests for my step                   -> pipeline-testing-doctor
```

Use `/pipeline-doctor` for a general architecture overview that helps you pick the right agent.

## Source of truth

The 13 runnable doc-test chapters define all conventions:

```text
nodejs/src/ingestion/pipelines/docs/
├── 01-introduction.test.ts
├── 02-batch-pipelines.test.ts
├── 03-concurrent-processing.test.ts
├── 04-sequential-processing.test.ts
├── 05-grouping.test.ts
├── 06-gathering.test.ts
├── 07-result-handling.test.ts
├── 08-side-effects.test.ts
├── 09-ingestion-warnings.test.ts
├── 10-branching.test.ts
├── 11-retries.test.ts
├── 12-filter-map.test.ts
└── 13-conventions.test.ts
```

## Adding conventions

When new framework features are added,
update the relevant doc-test chapter and agent definition together
so the rules stay in sync with the code.
