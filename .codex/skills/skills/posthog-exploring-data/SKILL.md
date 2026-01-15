---
name: posthog-exploring-data
description: Use this skill for querying and editing PostHog data created by the user in their project (actions, insights, surveys, dashboards, cohorts, feature flags, experiments, notebooks).
---

# PostHog Entities File System

This skill explains how to work with PostHog entities exported to the `.posthog/` directory.

## Overview

The `.posthog/` directory contains YAML representations of PostHog entities for the user's team. This is useful for understanding, searching, and modifying PostHog configurations.

## Entity Types

- Actions – unify multiple events or filtering conditions into one.
- Insights – visual and textual representation of the collected data aggregated by different types.
- Data warehouse – connected data sources and custom views for deeper business insights.
- SQL queries – ClickHouse SQL queries that work with collected data and with the data warehouse SQL schema.
- Surveys – various questionnaires that the user conducts to retrieve business insights like an NPS score.
- Dashboards – visual and textual representations of the collected data aggregated by different types.
- Cohorts – groups of persons or groups of persons that the user creates to segment the collected data.
- Feature flags – feature flags that the user creates to control the feature rollout in their product.
- Experiments – tests of different variations of the user's product to measure the impact.
- Notebooks – notebooks that the user creates to perform business analysis.
- Error tracking issues – issues that the user creates to track errors in their product.

## Directory Structure

```
.posthog/
  insights/
    {short_id}-{slug}.yaml      # e.g., abc123XY-weekly-active-users.yaml
  dashboards/
    {id}-{slug}.yaml            # e.g., 42-product-metrics-overview.yaml
  cohorts/
    {id}-{slug}.yaml            # e.g., 15-power-users.yaml
  actions/
    {id}-{slug}.yaml            # e.g., 7-signup-button-click.yaml
  experiments/
    {id}-{slug}.yaml            # e.g., 3-onboarding-ab-test.yaml
  feature_flags/
    {id}-{slug}.yaml            # e.g., 89-new-onboarding-flow.yaml
  _meta/
    config.json                 # Team ID, name, schema version
    sync_state.json             # Last sync timestamp
  _index/
    by_name.txt                 # Grep-friendly index: type:id:name
    references.json             # Cross-entity relationships
```

## File Format

Every YAML file has:

1. `_meta` - Sync metadata (read-only): type, id, checksum, timestamps, created_by
2. Entity fields - The actual configuration (editable)
3. `_refs` - Relationships to other entities (if any)

### Example Insight

```yaml
_meta:
  type: insight
  id: abc123XY
  db_id: 1234
  checksum: sha256:abc123...
  last_synced: '2024-01-15T10:30:00Z'
  created_by:
    id: 1
    email: user@example.com

name: 'Weekly Active Users'
description: 'Users with any event in last 7 days'
saved: true
favorited: false

query:
  kind: TrendsQuery
  series:
    - kind: EventsNode
      event: '$pageview'
      math: dau
  dateRange:
    date_from: '-7d'

_refs:
  dashboards: [42, 56]
```

### Example Feature Flag

```yaml
_meta:
  type: feature_flag
  id: 89
  version: 7
  checksum: sha256:...

key: new-onboarding-flow
name: 'Controls new onboarding flow access'
active: true
ensure_experience_continuity: true

filters:
  groups:
    - properties:
        - key: email
          type: person
          value: '@posthog.com'
          operator: icontains
      rollout_percentage: 100
    - properties: []
      rollout_percentage: 50

_refs:
  experiments: [3]
  cohorts: [15]
```

## Searching Entities

### Using the Index

```bash
# Find entity by name
grep -i "active" .posthog/_index/by_name.txt

# List all feature flags
grep "^feature_flag:" .posthog/_index/by_name.txt

# List all insights
grep "^insight:" .posthog/_index/by_name.txt
```

### Using Filenames

```bash
# Find insight by partial name
ls .posthog/insights/ | grep -i "active"

# Find feature flag by key
ls .posthog/feature_flags/ | grep -i "onboarding"
```

### Searching Content

```bash
# Find all active feature flags
grep -l "^active: true" .posthog/feature_flags/*.yaml

# Find insights using a specific event
grep -l "pageview" .posthog/insights/*.yaml

# Find entities referencing cohort 15
grep -rl "cohort.*15" .posthog/
```

## Understanding Relationships

The `_refs` section shows relationships:

- **Insights** reference dashboards they appear on
- **Dashboards** reference insights they contain
- **Experiments** reference their feature flag and exposure cohort
- **Feature flags** reference experiments using them and cohorts in their filters

Check `.posthog/_index/references.json` for a complete relationship graph.

## Tips for AI Agents

1. **Start with the index**: Read `.posthog/_index/by_name.txt` to find entities by name
2. **Use grep patterns**: The flat structure makes grep very effective
3. **Check references**: Use `_refs` to understand entity relationships
4. **Preserve `_meta`**: Don't modify the `_meta` section when editing
5. **Use checksums**: Compare `_meta.checksum` to detect changes
