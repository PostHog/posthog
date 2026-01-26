# Actions

## Action (`posthog_action`)

Actions are named combinations of events and conditions used for filtering and analysis.

### Columns

| Column                 | Type              | Nullable | Description                        |
| ---------------------- | ----------------- | -------- | ---------------------------------- |
| `id`                   | integer           | NOT NULL | Primary key (auto-generated)       |
| `name`                 | varchar(400)      | NULL     | Action name                        |
| `description`          | text              | NOT NULL | Action description                 |
| `deleted`              | boolean           | NOT NULL | Soft delete flag                   |
| `created_at`           | timestamp with tz | NOT NULL | Creation timestamp                 |
| `updated_at`           | timestamp with tz | NOT NULL | Last update timestamp              |
| `steps_json`           | jsonb             | NULL     | Action step definitions            |
| `post_to_slack`        | boolean           | NOT NULL | Whether to post matches to Slack   |
| `slack_message_format` | varchar(1200)     | NOT NULL | Slack message template             |
| `is_calculating`       | boolean           | NOT NULL | Whether calculation is in progress |
| `last_calculated_at`   | timestamp with tz | NOT NULL | Last calculation timestamp         |
| `bytecode`             | jsonb             | NULL     | Compiled action bytecode           |
| `bytecode_error`       | text              | NULL     | Compilation error message          |
| `pinned_at`            | timestamp with tz | NULL     | When action was pinned             |
| `summary`              | text              | NULL     | AI-generated summary               |
| `created_by_id`        | integer           | NULL     | FK to `posthog_user.id`            |

### HogQL Queryable Fields

Available via `system.actions`:

- `id`, `name`, `description`, `deleted`, `created_at`, `updated_at`, `steps_json`

### Steps JSON Structure

```json
[
  {
    "id": "uuid",
    "event": "$pageview",
    "url": "https://example.com/pricing",
    "url_matching": "contains",
    "properties": [{ "key": "$current_url", "value": "pricing", "operator": "icontains" }]
  },
  {
    "id": "uuid",
    "event": "button_clicked",
    "selector": "button.cta-primary",
    "text": "Sign Up",
    "text_matching": "exact"
  }
]
```

### Step Matching Options

| Field           | Description                  |
| --------------- | ---------------------------- |
| `event`         | Event name to match          |
| `url`           | URL pattern to match         |
| `url_matching`  | `exact`, `contains`, `regex` |
| `selector`      | CSS selector for element     |
| `text`          | Element text to match        |
| `text_matching` | `exact`, `contains`, `regex` |
| `properties`    | Additional property filters  |

### Key Relationships

- **Created By**: `created_by_id` -> `posthog_user.id`
- **Action Steps**: Legacy relationship via `posthog_actionstep` (deprecated, use `steps_json`)
- **Surveys**: Many-to-many via `posthog_survey_actions`

### Important Notes

- Actions can combine multiple event conditions (steps)
- Steps are OR'd together - matching any step triggers the action
- `bytecode` is compiled from steps for efficient evaluation
- Actions can be used in insights, cohorts, and feature flag targeting

---

## Common Query Patterns

**Find actions by name:**

```sql
SELECT id, name, description, steps_json
FROM system.actions
WHERE name ILIKE '%signup%' AND NOT deleted
```

**Find actions with specific event:**

```sql
SELECT id, name, steps_json
FROM system.actions
WHERE NOT deleted
  AND JSONExtractString(steps_json, 1, 'event') = '$pageview'
```
