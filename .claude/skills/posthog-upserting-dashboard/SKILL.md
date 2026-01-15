---
name: posthog-upsert-dashboard
description: Use this skill to create or update dashboards in the local .posthog/dashboards/ directory. Creates new dashboard YAML files or modifies existing ones with insights.
---

# Upsert Dashboard Skill

This skill enables creating and updating PostHog dashboards by editing YAML files in the `.posthog/dashboards/` directory. Use in combination with skills:

- `posthog-exporing-data` to understand how to explore data in PostHog.
- `posthog-exploring-data-schema` to understand what events, properties, and property values exist in PostHog.
- `posthog-creating-insight` to create new insights.

## Overview

Use this skill when:

- The user asks to create or update a dashboard
- The user asks for multiple metrics or dimensions that would be better visualized in a dashboard
- The user wants to modify insights on an existing dashboard (add, remove, or replace)

Do NOT use this skill when:

- The user wants to save a single insight (use insight creation instead)

## Dashboard File Format

Dashboard YAML files are stored at `.posthog/dashboards/{id}-{slug}.yaml`

### Structure

```yaml
_meta:
  type: dashboard
  id: 42
  checksum: sha256:abc123...
  last_synced: '2024-01-15T10:30:00Z'
  created_by:
    id: 1
    email: user@example.com

name: 'Product Metrics Overview'
description: 'Key metrics for tracking product health'

_refs:
  insights: ['abc123XY', 'def456AB', 'ghi789CD']
```

### Fields

| Field            | Description                                          |
| ---------------- | ---------------------------------------------------- |
| `_meta`          | Sync metadata (read-only) - do not modify            |
| `name`           | Short, concise name (3-7 words)                      |
| `description`    | Brief description of the dashboard's purpose         |
| `_refs.insights` | List of insight short_ids included in this dashboard |

## How to Use

Keep track of todo list when upserting a dashboard.

### Create vs Update Decision

1. **Search first**: Use grep or the index to check if a relevant dashboard and insights already exists
2. **Ask if ambiguous**: If the request is unclear, ask whether to create new or update existing
3. **Understand existing**: If updating, read the dashboard file to understand its current structure

### Choose insights

1. Search for saved insights first that match user's request.
2. Read their schemas to understand if they match.
3. Explore data schema to find relevant events, properties, and property values.
4. Explore saved actions in order to find matching.
5. Optionally, create new insights using the skill.

### Creating a New Dashboard

1. Create a new file at `.posthog/dashboards/{id}-{slug}.yaml`
2. Generate a unique numeric ID (check existing files for the highest ID)
3. Create a slug from the name (lowercase, hyphens, no special chars)
4. Include all required fields

```yaml
_meta:
  type: dashboard
  id: 99
  checksum: ''
  last_synced: ''

name: 'Weekly User Activity'
description: 'Track user engagement metrics on a weekly basis'

_refs:
  insights: ['abc123XY', 'def456AB']
```

### Updating an Existing Dashboard

When updating `_refs.insights`, the new list **replaces all existing insights**.

**Positional layout mapping**: The order of insight IDs determines their position:

- First insight takes the first tile's position
- Second insight takes the second tile's position
- And so on...

**Example**: Dashboard has insights `[A, B, C]`. Update with `[A', C']`:

- Result: `A'` takes `A`'s position, `C'` takes `B`'s position, `C` is removed

### Adding Insights to a Dashboard

To add new insights without removing existing ones:

1. Read the current `_refs.insights` list
2. Append the new insight IDs
3. Write the updated list

### Removing Insights from a Dashboard

To remove insights:

1. Read the current `_refs.insights` list
2. Remove the unwanted insight IDs
3. Write the updated list

### Replacing Insights on a Dashboard

To replace specific insights:

1. Read the current `_refs.insights` list
2. Substitute old insight IDs with new ones (maintain order for layout)
3. Write the updated list

## Searching for Dashboards

```bash
# Find dashboard by name
grep -i "metrics" .posthog/_index/by_name.txt | grep "^dashboard:"

# List all dashboards
ls .posthog/dashboards/

# Find dashboard containing specific insight
grep -l "abc123XY" .posthog/dashboards/*.yaml
```

## Guidelines

1. **Minimal changes**: Use the minimal set of insights needed to fulfill the request
2. **Preserve existing**: When updating, maintain existing insight references unless explicitly asked to remove them
3. **Naming conventions**:
   - Names: 3-7 words, descriptive, sentence case
   - Descriptions: One concise sentence explaining the dashboard's purpose
4. **Reference integrity**: Ensure all insight IDs in `_refs.insights` correspond to valid insight files in `.posthog/insights/`
5. **Don't modify `_meta`**: The `_meta` section is managed by the sync system

## Cross-References

Dashboards reference insights via `_refs.insights`. Conversely, insight files have `_refs.dashboards` listing which dashboards include them.

When adding/removing insights from a dashboard, consider updating the corresponding insight files' `_refs.dashboards` for consistency.
