# Weekly Digest

The weekly digest is an email sent to all customers summarizing activity in their PostHog projects over the past week.

## Architecture Overview

The digest is generated and sent via two Temporal workflows:

1. **GenerateDigestDataWorkflow** - Generates all digest data and stores it in Redis
2. **SendWeeklyDigestWorkflow** - Reads from Redis and sends personalized emails

## Redis Storage Structure

Data is stored with keys prefixed by `{digest_key}` (e.g., `weekly-digest-2024-01`).

**Important:** All Redis keys are generated via helper functions in `keys.py`. Never hardcode key strings - use the typed enums and generator functions instead.

### Team-level data

Generated via `team_data_key(digest_key, TeamDataKey.*, team_id)`:

| `TeamDataKey` enum      | Key Pattern                                    | Contents                           |
| ----------------------- | ---------------------------------------------- | ---------------------------------- |
| `DASHBOARDS`            | `{digest_key}-dashboards-{team_id}`            | New dashboards created             |
| `EVENT_DEFINITIONS`     | `{digest_key}-event-definitions-{team_id}`     | New event definitions              |
| `EXPERIMENTS_LAUNCHED`  | `{digest_key}-experiments-launched-{team_id}`  | Experiments started                |
| `EXPERIMENTS_COMPLETED` | `{digest_key}-experiments-completed-{team_id}` | Experiments finished               |
| `EXTERNAL_DATA_SOURCES` | `{digest_key}-external-data-sources-{team_id}` | New data sources                   |
| `FEATURE_FLAGS`         | `{digest_key}-feature-flags-{team_id}`         | New feature flags                  |
| `SAVED_FILTERS`         | `{digest_key}-saved-filters-{team_id}`         | Interesting replay filters         |
| `EXPIRING_RECORDINGS`   | `{digest_key}-expiring-recordings-{team_id}`   | Count of soon-to-expire recordings |
| `SURVEYS_LAUNCHED`      | `{digest_key}-surveys-launched-{team_id}`      | Surveys launched                   |

### Organization-level data

Generated via `org_digest_key(digest_key, org_id)`:

| Key Pattern             | Contents                                                      |
| ----------------------- | ------------------------------------------------------------- |
| `{digest_key}-{org_id}` | `OrganizationDigest` containing all team digests for that org |

### User-level data

Generated via `user_data_key(digest_key, UserDataKey.*, user_id)`:

| `UserDataKey` enum   | Key Pattern                                 | Contents                                                        |
| -------------------- | ------------------------------------------- | --------------------------------------------------------------- |
| `NOTIFY_TEAMS`       | `{digest_key}-user-notify-{user_id}`        | Redis SET of team IDs the user should receive notifications for |
| `PRODUCT_SUGGESTION` | `{digest_key}-product-suggestion-{user_id}` | Single `DigestProductSuggestion` for product recommendations    |

## Data Flow

```plaintext
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GenerateDigestDataWorkflow                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Count teams & orgs for batching                                         │
│                                                                             │
│  2. Generate team-level data (parallel per batch):                          │
│     ├── generate_dashboard_lookup                                           │
│     ├── generate_event_definition_lookup                                    │
│     ├── generate_experiment_launched_lookup                                 │
│     ├── generate_experiment_completed_lookup                                │
│     ├── generate_external_data_source_lookup                                │
│     ├── generate_feature_flag_lookup                                        │
│     ├── generate_survey_lookup                                              │
│     ├── generate_filter_lookup                                              │
│     ├── generate_recording_lookup                                           │
│     ├── generate_user_notification_lookup                                   │
│     └── generate_product_suggestion_lookup                                  │
│                                                                             │
│  3. Aggregate into org digests:                                             │
│     └── generate_organization_digest_batch                                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                              Redis Storage
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SendWeeklyDigestWorkflow                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  For each organization (batched):                                           │
│    1. Load OrganizationDigest from Redis                                    │
│    2. For each org member:                                                  │
│       a. Load user's notification team set                                  │
│       b. Load user's product suggestion                                     │
│       c. Create UserSpecificDigest via org_digest.for_user()                │
│       d. Render payload and send via PostHog capture event                  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Key Types

### OrganizationDigest

The base digest containing all team data for an organization. Stored in Redis.

### UserDigestContext

Container for all user-specific data. This is where you add new user-specific fields:

```python
class UserDigestContext(BaseModel):
    product_suggestion: DigestProductSuggestion | None = None
    # Add new user-specific fields here
```

### UserSpecificDigest

A personalized view created at send time by calling `OrganizationDigest.for_user(user_teams, context)`. Contains:

- Filtered team digests (only teams user has notifications enabled for)
- `context`: A `UserDigestContext` with user-specific data

This is **not stored on Redis** - it's computed on-the-fly during the send phase.

### DigestProductSuggestion

A product recommendation for a user, containing:

- `team_id`: Which project the suggestion is for
- `product_path`: The product name (e.g., "Session replay")
- `reason`: Why it was suggested (enum value)
- `reason_text`: Human-readable explanation for the email

## Adding New Team-Level Fields

Team-level fields are data that belongs to a project/team (dashboards, feature flags, etc.). Each field type should have its own activity method to keep concerns separated and allow parallel execution.

1. **Add a new enum value to `TeamDataKey`** in `keys.py`:

   ```python
   class TeamDataKey(StrEnum):
       # ... existing keys ...
       ALERTS = "alerts"  # new
   ```

2. **Create a Pydantic model** in `types.py` for the new data type (e.g., `DigestAlert`, `AlertList`)

3. **Add a query function** in `queries.py` to fetch the data from the database

4. **Create a new activity** in `activities.py`:

   ```python
   @activity.defn(name="generate-alert-lookup")
   async def generate_alert_lookup(input: GenerateDigestDataBatchInput) -> None:
       return await generate_digest_data_lookup(
           input,
           key_kind=TeamDataKey.ALERTS,
           query_func=query_new_alerts,
           resource_type=AlertList,
       )
   ```

5. **Register the activity** in `workflows.py` by adding it to the `generators` list in `GenerateDigestDataWorkflow`

6. **Add the field to `TeamDigest`** in `types.py` and update `generate_organization_digest_batch` to load it from Redis (the key order in `all_team_data_keys` matches `TeamDataKey` enum order)

7. **Update `TeamDigest.render_payload()`** to include the new field in the email payload

## Adding New User-Specific Fields

User-specific fields are data personalized per user (product suggestions, notification preferences, etc.). Each field type should have its own activity method for loading data during the generate phase.

1. **Add a new enum value to `UserDataKey`** in `keys.py`:

   ```python
   class UserDataKey(StrEnum):
       # ... existing keys ...
       RECOMMENDATIONS = "recommendations"  # new
   ```

2. **Create a Pydantic model** in `types.py` for the new data type

3. **Add a query function** in `queries.py` to fetch the data

4. **Create a new activity** in `activities.py` to generate and store the data in Redis:

   ```python
   @activity.defn(name="generate-user-recommendations-lookup")
   async def generate_user_recommendations_lookup(input: GenerateDigestDataBatchInput) -> None:
       # Iterate through teams/users, query data, store in Redis using:
       key = user_data_key(input.digest.key, UserDataKey.RECOMMENDATIONS, user.id)
   ```

5. **Register the activity** in `workflows.py` by adding it to the `generators` list

6. **Add the field to `UserDigestContext`** in `types.py`:

   ```python
   class UserDigestContext(BaseModel):
       product_suggestion: DigestProductSuggestion | None = None
       recommendations: UserRecommendations | None = None  # new field
   ```

7. **Load the data in `send_weekly_digest_batch`** and set it on the context:

   ```python
   raw_recommendations = await r.get(
       user_data_key(input.digest.key, UserDataKey.RECOMMENDATIONS, user.id)
   )
   recommendations = UserRecommendations.model_validate_json(raw_recommendations) if raw_recommendations else None

   user_context = UserDigestContext(
       product_suggestion=product_suggestion,
       recommendations=recommendations,
   )
   ```

8. **Use it in `UserSpecificDigest.render_payload()`** to include in the email payload

The `for_user()` signature never changes - all user-specific data flows through `UserDigestContext`.
