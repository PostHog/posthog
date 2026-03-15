# Sandboxed Agent Eval Harness — Design Document

## Problem

PostHog's sandboxed coding agent (`@posthog/agent`) runs in Docker/Modal containers,
clones repositories, writes code, and creates PRs.
Currently there is no eval system for this agent —
only the Max AI chat agent has evals (in `ee/hogai/eval/`).

We need an eval harness to measure and track agent quality over time.

## Research basis

This design is informed by:

- **Anthropic's agent eval guidelines** — grade outcomes not paths, layered scoring
  (deterministic first, LLM judges for subjective quality), isolated execution,
  pass@k consistency metrics, start small with 20–50 tasks
- **OpenAI Codex / SWE-bench** — containerized Docker harness for reproducibility,
  fail-to-pass test validation, repo + issue → patch → run tests
- **Industry best practices** — partial credit for multi-component tasks,
  separate scoring dimensions, don't check tool call sequences

## Architecture

```
ee/hogai/eval/sandboxed/
├── config.py            # SandboxEvalConfig, SandboxedEvalCase, AgentArtifacts
├── runner.py            # SandboxedEvalRunner (sandbox lifecycle + artifact collection)
├── base.py              # SandboxedEval, SandboxedPublicEval, SandboxedPrivateEval
├── scorers/
│   ├── deterministic.py # TestsPass, LintClean, FilesModified, ExitCodeZero, etc.
│   ├── llm_judge.py     # CodeQuality, InstructionAdherence, PRDescriptionQuality
│   └── composite.py     # WeightedScorer, PartialCreditScorer
├── fixtures/
│   └── repos.py         # create_temp_repo(), bugfix_repo(), feature_repo()
├── conftest.py          # pytest fixtures
├── pytest.ini           # eval-specific pytest config
└── ci/
    └── eval_basic.py    # example eval cases (placeholder)
```

## Execution flow

```
pytest collects eval cases
  └─► For each SandboxedEvalCase:
        1. Build repo from fixture (create_temp_repo)
        2. Create DockerSandbox with SandboxConfig
        3. Copy repo into sandbox
        4. Run agent via runAgent.mjs --prompt "..." --repositoryPath ...
        5. Collect artifacts:
           - git diff, files changed
           - test suite results (pytest exit code + output)
           - lint results (ruff exit code + output)
           - agent exit code, stdout, stderr, duration
        6. Run scorers against AgentArtifacts
        7. Report to Braintrust
        8. Cleanup sandbox
```

## Scoring approach

### Layer 1: Deterministic (fast, objective)

| Scorer | Score type | Description |
|--------|-----------|-------------|
| `ExitCodeZero` | Binary | Agent exited cleanly |
| `GitDiffNonEmpty` | Binary | Agent made changes |
| `TestsPass` | Binary | Test suite passes |
| `LintClean` | Binary | Linter passes |
| `FilesModified` | Partial | Fraction of expected files modified |
| `NoBrokenTests` | Partial | Fraction of tests still passing |

### Layer 2: LLM judges (slower, subjective)

| Scorer | Description |
|--------|-------------|
| `CodeQuality` | Correctness, readability, minimality, style, safety |
| `InstructionAdherence` | Did the agent do what was asked? |
| `PRDescriptionQuality` | Quality of PR title and description |

### Layer 3: Composite

| Scorer | Description |
|--------|-------------|
| `WeightedScorer` | Weighted combination of sub-scorers |
| `PartialCreditScorer` | Mean of non-None sub-scores |

## Synthetic test repos

Small, purpose-built git repos created with `create_temp_repo()`:

- **Bug fix**: repo with a failing test, agent should fix the code
- **Feature add**: repo with skipped tests, agent should implement the feature
- **Refactor**: repo with working but messy code (future)
- **PR creation**: repo with a task requiring a PR (future)

## Integration points

- **Braintrust**: Uses `EvalAsync` for experiment tracking (same as Max AI evals)
- **DockerSandbox**: Reuses `products/tasks/backend/services/docker_sandbox.py`
- **SandboxConfig**: Reuses `products/tasks/backend/services/sandbox.py`
- **runAgent.mjs**: Invokes the agent via `products/tasks/scripts/runAgent.mjs`

## Consistency metrics

For pass@k measurement, set `SandboxEvalConfig.trials = k`.
The harness runs each case `k` times independently,
enabling pass@k (at least 1 success) and pass^k (all succeed) computation.

## Next steps

1. Add real eval cases once Docker sandbox images are built
2. Add CI integration (similar to `ee/hogai/eval/ci/`)
3. Add offline eval mode via Dagster
4. Track token usage and cost per eval case
5. Add refactoring and PR-creation eval fixtures
