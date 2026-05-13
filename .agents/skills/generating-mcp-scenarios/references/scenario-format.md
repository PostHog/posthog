# Scenario format

Each scenario is a YAML file representing one user workflow.
Scenarios live in `services/mcp/tests/scenarios/<domain>/`.

## Schema

```yaml
# Required fields
name: create-trends-insight-with-breakdown
description: >
  User asks to create a trends insight showing pageview events
  over the last 7 days, broken down by browser.
domain: product-analytics
tools_in_scope:
  - trends-query-run
  - insight-create

prompt: |
  I want to see how many pageview events we've had over the last 7 days,
  broken down by browser. Create an insight for this and save it so I can
  come back to it later.

success_criteria:
  - All tool calls complete without error
  - Created insight uses $pageview event
  - Breakdown configured on browser property
  - Insight is retrievable after creation

# Optional fields
generated_from:
  pr: 12345
  commit: abc1234def
  changed_files:
    - products/product_analytics/backend/api/insights.py
    - products/product_analytics/mcp/tools.yaml
tags:
  - crud
  - insights
  - breakdown
```

## Field reference

| Field              | Required | Description                                                                                                                                           |
| ------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `name`             | yes      | Kebab-case identifier, unique within the domain. Used as the filename (without `.yaml`).                                                              |
| `description`      | yes      | One-paragraph explanation of what the scenario tests and why.                                                                                         |
| `domain`           | yes      | Maps to the subdirectory under `services/mcp/tests/scenarios/`. Use the product name (e.g., `product-analytics`, `feature-flags`, `experiments`).     |
| `tools_in_scope`   | yes      | MCP tool names expected to be called during execution. Not a strict checklist — the executor may call additional tools for discovery or verification. |
| `prompt`           | yes      | The natural-language prompt fed to the executor subprocess. Write this as a real user would talk to an agent.                                         |
| `success_criteria` | yes      | Bullet list of conditions that must all be true for a pass. Be specific and verifiable.                                                               |
| `generated_from`   | no       | Traceability metadata — which PR/commit/files prompted this scenario.                                                                                 |
| `tags`             | no       | Freeform tags for filtering and grouping.                                                                                                             |

## Writing good prompts

The prompt is the most important field.
It should read like a real person asking an agent for help.

**Do:**

- Use natural language, not technical specifications
- Include enough context that the agent knows what "success" looks like
- Ask for verification ("and show me the result", "confirm it was saved")
- Reference realistic data (event names, property names, date ranges)

**Don't:**

- Name specific tool names ("call the trends-query-run tool") — let the agent discover them
- Specify exact API parameters — describe the intent, not the implementation
- Include multiple unrelated workflows in one prompt — one scenario per file

### Good example

```yaml
prompt: |
  I'm trying to understand our onboarding funnel. Can you show me the
  conversion rate from sign-up to first project creation over the last
  30 days? Break it down by the referring domain so I can see which
  channels convert best. Save this as a dashboard insight called
  "Onboarding funnel by referrer".
```

### Bad example

```yaml
prompt: |
  Call funnel-query-run with events [$signed_up, $project_created],
  date_from=-30d, breakdown_type=event, breakdown=$referring_domain.
  Then call insight-create with the result.
```

## Writing good success criteria

Each criterion should be independently verifiable by examining tool responses.

**Do:**

- Reference specific fields in the expected response
- Include both "it worked" and "it worked correctly" criteria
- Check side effects (was it actually persisted? can it be retrieved?)

**Don't:**

- Use vague criteria ("the result looks right")
- Require subjective judgment ("the response is well-formatted")
- Check timing or performance (that's a different concern)

### Good criteria

```yaml
success_criteria:
  - Funnel query returns results with at least 2 steps
  - Breakdown by $referring_domain is present in the response
  - insight-create returns a 201 with an id field
  - insight-get with that id returns the saved insight
  - The saved insight's filters match the funnel configuration
```

### Bad criteria

```yaml
success_criteria:
  - It works
  - The response looks correct
  - No errors
```

## Organizing scenarios

```text
services/mcp/tests/scenarios/
  product-analytics/
    create-trends-insight-with-breakdown.yaml
    query-funnel-conversion-by-referrer.yaml
    retention-cohort-weekly.yaml
  feature-flags/
    create-and-toggle-flag.yaml
    flag-with-multivariate-rollout.yaml
  experiments/
    launch-experiment-with-holdout.yaml
    check-experiment-results.yaml
  surveys/
    create-nps-survey.yaml
    analyze-survey-responses.yaml
  error-tracking/
    list-and-triage-errors.yaml
  data-warehouse/
    query-external-table.yaml
  core/
    search-and-retrieve-dashboard.yaml
    manage-annotations.yaml
```

Use the product name as the domain directory.
If a scenario spans multiple products, put it in the primary product's directory.

## Deduplication

Before creating a new scenario, search for existing ones:

```bash
grep -r "tools_in_scope" services/mcp/tests/scenarios/ | grep "tool-name"
```

If an existing scenario covers the same workflow:

- Update it if the behavior changed
- Extend it if the PR adds new capabilities to the same flow
- Create a new one only if the PR introduces a genuinely different workflow
