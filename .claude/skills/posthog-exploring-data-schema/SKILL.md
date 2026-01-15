---
name: Explore PostHog Data Schema
description: Explains how to use PostHog CLI to explore data schema of a PostHog project including events, their properties, and property values.
---

# PostHog Data Schema Explorer

Use this skill to explore the user's PostHog taxonomy (data schema) by running HogQL queries directly against their project.

The user implements PostHog SDKs to collect events, properties, and property values. They are used to create insights with visualizations, SQL queries, watch session recordings, filter data, target particular users or groups by traits or behavior, etc.

Each event, action, and entity has its own data schema. You must verify that specific combinations exist before using it anywhere else.

Events or properties starting from "$" are system properties automatically captured by SDKs.

**CRITICAL**: Do not rely on your training data or PostHog defaults for events or properties. Always use this skill to confirm what actually exists in the user's project before referencing any event, property, or property value.

## When to Use This Skill

Use this skill proactively when:

1. The user asks about **their custom data schema** in PostHog
2. You need to find specific combinations of events, properties, and property values
3. The user wants to track specific metrics or behaviors
4. You need to verify what events or properties exist in their project
5. You're building a query or insight and need to know available data

### Examples of When to Use

**Example 1: Finding revenue tracking events**

```
User: What event can I use to track revenue?
Assistant: I'm going to retrieve events and event properties to help you find the event you're looking for.
*Uses this skill to retrieve events*
Assistant: I've found a few matching events. I'm going to retrieve event properties to help you find the event you're looking for.
*Uses this skill to retrieve event properties for each event*
Assistant: I've found a few matching properties. I'm going to retrieve sample property values for each property to verify they can be used for revenue tracking.
*Uses this skill to retrieve sample property values*
Assistant: I've found matching combinations...
```

**Example 2: Exploring person properties**

```
User: What properties do we track on users?
Assistant: Let me retrieve person properties from your PostHog project.
*Uses this skill to retrieve person properties*
```

## When NOT to Use This Skill

Skip this skill when:

- The user is asking about PostHog documentation or general concepts
- The task is purely informational and doesn't require project-specific data
- You're not referencing specific events, properties, or values from their project

## How to Use This Skill

This skill uses the `posthog-cli exp query run` command to execute HogQL queries. The CLI will return JSON Lines output that you should parse to extract the data.

### Available Queries

#### 1. Get Top Events (Last 30 Days)

Retrieves the most popular events sorted by count.

```bash
posthog-cli exp query run "SELECT event, count() as count FROM events WHERE timestamp >= now() - INTERVAL 30 DAY GROUP BY event ORDER BY count DESC LIMIT 500"
```

**Output format**: Each line contains `{"event": "event_name", "count": 12345}`

**When to use**: When you need to see what events are available or find the most commonly used events.

#### 2. Get Event Properties

Retrieves properties and sample values for a specific event (last 30 days).

Replace `EVENT_NAME` with the actual event name:

```bash
posthog-cli exp query run "SELECT key, arraySlice(arrayDistinct(groupArray(value)), 1, 5) AS values, count(distinct value) AS total_count FROM (SELECT JSONExtractKeysAndValues(properties, 'String') as kv FROM events WHERE timestamp >= now() - INTERVAL 30 DAY AND event = 'EVENT_NAME' ORDER BY timestamp desc LIMIT 100) ARRAY JOIN kv.1 AS key, kv.2 AS value WHERE NOT match(key, '(\$set|\$time|\$set_once|\$sent_at|distinct_id|\$ip|\$feature\/|__|phjs|survey_dismissed|survey_responded|partial_filter_chosen|changed_action|window-id|changed_event|partial_filter|distinct_id)') GROUP BY key ORDER BY total_count DESC LIMIT 500"
```

**Output format**: Each line contains `{"key": "property_name", "values": ["val1", "val2", ...], "total_count": 10}`

**When to use**: When you need to see what properties are available for a specific event.

#### 3. Get Event Property Values

Retrieves sample values for a specific property on a specific event.

Replace `EVENT_NAME` and `PROPERTY_NAME` with actual values:

```bash
posthog-cli exp query run "SELECT key, arraySlice(arrayDistinct(groupArray(value)), 1, 25) AS values, count(DISTINCT value) AS total_count FROM (SELECT key, value, count() as count FROM (SELECT [('PROPERTY_NAME', JSONExtractString(properties, 'PROPERTY_NAME'))] as kv FROM events WHERE timestamp >= now() - INTERVAL 30 DAY AND event = 'EVENT_NAME' AND JSONExtractString(properties, 'PROPERTY_NAME') != '') ARRAY JOIN kv.1 AS key, kv.2 AS value WHERE value != '' GROUP BY key, value ORDER BY count DESC) GROUP BY key LIMIT 500"
```

**Output format**: Each line contains `{"key": "property_name", "values": ["val1", "val2", ...], "total_count": 10}`

**When to use**: When you need to see what values exist for a specific property on an event.

#### 4. Get Person Properties

Retrieves properties available on person entities.

```bash
posthog-cli exp query run "SELECT DISTINCT key FROM (SELECT arrayJoin(JSONExtractKeys(properties)) as key FROM persons) WHERE key != '' LIMIT 200"
```

**Output format**: Each line contains `{"key": "property_name"}`

**When to use**: When you need to see what properties are tracked on persons/users.

#### 5. Get Person Property Values

Retrieves sample values for a specific person property.

Replace `PROPERTY_NAME` with the actual property name:

```bash
posthog-cli exp query run "SELECT groupArray(prop, 25) as sample_values, count() as sample_count FROM (SELECT DISTINCT toString(properties.PROPERTY_NAME) as prop FROM persons WHERE isNotNull(properties.PROPERTY_NAME) ORDER BY created_at DESC)"
```

**Output format**: `{"sample_values": ["val1", "val2", ...], "sample_count": 10}`

**When to use**: When you need to see what values exist for a specific person property.

#### 6. Get Session Properties

Similar to person properties but for sessions. Replace `persons` with `sessions` in the queries above.

#### 7. Get Group Properties

For group analytics, you can query group properties. Replace `persons` with `groups` and add a filter for the group type index.

Replace `GROUP_TYPE_INDEX` and `PROPERTY_NAME` with actual values:

```bash
posthog-cli exp query run "SELECT groupArray(prop, 25) as sample_values, count() as sample_count FROM (SELECT DISTINCT toString(properties.PROPERTY_NAME) as prop FROM groups WHERE isNotNull(properties.PROPERTY_NAME) AND index = GROUP_TYPE_INDEX ORDER BY created_at DESC)"
```

## Important Notes

1. **Always filter system events**: The queries automatically filter out system events that start with `$` and are marked as `system` or `ignored_in_assistant` in PostHog's core definitions.

2. **Privacy properties are omitted**: Properties like `$ip` are automatically filtered out.

3. **30-day window**: Most queries look at data from the last 30 days to balance performance and relevance.

4. **Property limits**:
   - Event properties: Returns top 500 properties
   - Sample values: Returns up to 5-25 sample values per property
   - Events: Returns top 500 events by count

5. **Parsing output**: The CLI returns JSON Lines format (one JSON object per line). You'll need to parse each line as JSON.

6. **Error handling**: If a query fails, the CLI will return an error. Make sure to check for errors and adjust the query if needed.

## Example Workflow

When a user asks "How can I track checkout completions?", follow this workflow:

1. **Get top events** to see what events exist
2. **Filter for relevant events** (e.g., those containing "checkout", "purchase", "order")
3. **Get properties for each candidate event** to see what data is available
4. **Get sample values for key properties** to verify the data structure
5. **Present findings** with concrete examples from their actual data

This ensures you're giving advice based on their real data, not assumptions.

## Tips

- Use `jq` to parse and filter JSON Lines output: `posthog-cli exp query run "..." | jq -r '.event'`
- When event or property names contain special characters, make sure to properly escape them in the SQL query
- Single quotes for string literals in HogQL, double quotes for identifiers if needed
- Test queries incrementally - start with simple queries and add filters as needed
