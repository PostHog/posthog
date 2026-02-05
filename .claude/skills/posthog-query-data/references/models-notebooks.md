# Notebooks

## Notebook (`system.notebooks`)

Notebooks are collaborative documents combining text, insights, and code.

### Columns

Column | Type | Nullable | Description
`id` | uuid | NOT NULL | Primary key (UUID)
`short_id` | varchar(12) | NOT NULL | Unique short identifier for URLs
`title` | varchar(256) | NULL | Notebook title
`content` | jsonb | NULL | Notebook content blocks
`text_content` | text | NULL | Plain text extraction for search
`deleted` | boolean | NOT NULL | Soft delete flag
`visibility` | varchar(20) | NOT NULL | `private`, `shared`, or `public`
`version` | integer | NOT NULL | Content version number
`created_at` | timestamp with tz | NOT NULL | Creation timestamp
`last_modified_at` | timestamp with tz | NOT NULL | Last modification timestamp
`created_by_id` | integer | NULL | Creator user ID
`last_modified_by_id` | integer | NULL | Last modifier user ID
`team_id` | integer | NOT NULL | FK to `system.teams.id`
`kernel_cpu_cores` | double precision | NULL | Jupyter kernel CPU allocation
`kernel_memory_gb` | double precision | NULL | Jupyter kernel memory allocation
`kernel_idle_timeout_seconds` | integer | NULL | Kernel idle timeout

### Content Structure

Notebooks use a block-based content format:

```json
{
  "type": "doc",
  "content": [
    {
      "type": "heading",
      "attrs": {"level": 1},
      "content": [{"type": "text", "text": "Analysis Report"}]
    },
    {
      "type": "paragraph",
      "content": [{"type": "text", "text": "This notebook analyzes..."}]
    },
    {
      "type": "ph-query",
      "attrs": {
        "query": {"kind": "TrendsQuery", ...},
        "title": "Daily Active Users"
      }
    },
    {
      "type": "ph-recording-playlist",
      "attrs": {"filters": {...}}
    }
  ]
}
```

### Block Types

Type | Description
`heading` | Header text (h1-h6)
`paragraph` | Text paragraph
`ph-query` | Embedded insight/query
`ph-recording-playlist` | Session recording list
`ph-person` | Person profile embed
`ph-cohort` | Cohort embed
`ph-feature-flag` | Feature flag embed
`codeBlock` | Code snippet

### Key Relationships

- **Team**: `team_id` -> `system.teams.id` (required)

### Important Notes

- `short_id` is unique per team and used in URLs: `/notebooks/{short_id}`
- `text_content` is auto-extracted from `content` for full-text search
- Visibility controls who can view/edit the notebook
- Notebooks support real-time collaboration via version tracking

---

## Common Query Patterns

**List notebooks by title:**

```sql
SELECT id, short_id, title, visibility, last_modified_at
FROM system.notebooks
WHERE title ILIKE '%analysis%' AND NOT deleted
ORDER BY last_modified_at DESC
LIMIT 20
```

**Find notebooks with specific content:**

```sql
SELECT id, short_id, title
FROM system.notebooks
WHERE NOT deleted
  AND text_content ILIKE '%retention%'
```
