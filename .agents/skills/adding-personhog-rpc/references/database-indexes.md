# Database indexes for personhog tables

Every personhog query must use an index scan.
Before designing your RPC, verify your WHERE clause matches one of these indexes.

All tables below have `managed = False` in Django — migrations are managed by `rust/persons_migrations`, not Django.

## posthog_person

Partitioned by `team_id` (64 hash partitions).
Primary key is composite `(team_id, id)`.

| Index             | Columns                  | Notes                                                 |
| ----------------- | ------------------------ | ----------------------------------------------------- |
| PK (composite)    | `(team_id, id)`          | Partition-pruned lookup by team_id + id               |
| uuid index        | `uuid`                   | `db_index=True` on uuid field                         |
| team_id + id DESC | `(team_id, id DESC)`     | Migration 0164, used for batch deletes and pagination |
| email JSON index  | `(properties->>'email')` | Migration 0121, functional index on JSON property     |

**Typical query patterns:**

- `WHERE team_id = $1 AND id = $2` → PK scan
- `WHERE team_id = $1 AND uuid = $2` → uuid index (partition-pruned)
- `WHERE team_id = $1 AND id = ANY($2)` → PK scan
- `WHERE team_id = $1 AND uuid = ANY($2)` → uuid index scan

## posthog_persondistinctid

| Index             | Columns                  | Notes                                      |
| ----------------- | ------------------------ | ------------------------------------------ |
| Unique constraint | `(team_id, distinct_id)` | Primary lookup path                        |
| FK to person      | `(team_id, person_id)`   | Composite FK to partitioned posthog_person |

**Typical query patterns:**

- `JOIN posthog_persondistinctid d ON p.id = d.person_id AND p.team_id = d.team_id WHERE d.team_id = $1 AND d.distinct_id = $2` → unique constraint scan
- `WHERE team_id = $1 AND person_id = $2` → FK index scan

## posthog_group

| Index             | Columns                                  | Notes               |
| ----------------- | ---------------------------------------- | ------------------- |
| Unique constraint | `(team_id, group_key, group_type_index)` | Primary lookup path |

**Typical query patterns:**

- `WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3` → unique constraint scan
- `WHERE team_id = $1 AND group_type_index = $2` → partial constraint scan (for listing)

## posthog_grouptypemapping

| Index                      | Columns                          | Notes                           |
| -------------------------- | -------------------------------- | ------------------------------- |
| project + group_type       | `(project_id, group_type)`       | `posthog_group_type_proj_idx`   |
| project + group_type_index | `(project_id, group_type_index)` | `posthog_group_type_i_proj_idx` |

**Typical query patterns:**

- `WHERE team_id = $1` → needs seq scan unless team_id has an implicit index (FK)
- `WHERE project_id = $1` → uses project indexes above
- `WHERE project_id = $1 AND group_type_index = $2` → uses `posthog_group_type_i_proj_idx`

## posthog_cohortpeople

| Index           | Columns                  | Notes               |
| --------------- | ------------------------ | ------------------- |
| Composite index | `(cohort_id, person_id)` | Primary lookup path |

**Typical query patterns:**

- `WHERE cohort_id = $1 AND person_id = $2` → composite index scan
- `WHERE cohort_id = $1` → index scan (leading column)

## posthog_featureflaghashkeyoverride

| Index             | Columns                                  | Notes               |
| ----------------- | ---------------------------------------- | ------------------- |
| Unique constraint | `(team_id, person_id, feature_flag_key)` | Primary lookup path |

Note: FK fields have `db_index=False` — lookups must go through the unique constraint.

**Typical query patterns:**

- `WHERE team_id = $1 AND person_id = $2` → partial unique constraint scan (leading columns)

## posthog_personoverride

| Index             | Columns                               | Notes               |
| ----------------- | ------------------------------------- | ------------------- |
| Unique constraint | `(team_id, old_person_id)`            | Primary lookup path |
| Check constraint  | `old_person_id != override_person_id` | Integrity check     |

## If you need a new index

If your query can't use an existing index, you need a new migration in `rust/persons_migrations` before adding the RPC.
Discuss with the team first — new indexes on large partitioned tables have operational implications.
