---
name: posthog-creating-insight
description: Creates an insight for your analysis based on PostHog data (trends, funnel, retention). Use this tool to analyze user's users, organizations, events, actions, data warehouse events, etc.
---

# Create Insight Skill

This skill enables creating PostHog insight plans by writing YAML files to the `.posthog/insights/` directory.

## Overview

Use this skill when:

- The user asks to create a new insight (trends, funnel, or retention)
- The user wants to plan an insight before executing it
- The user needs help structuring an insight query

Do NOT use this skill when:

- The user wants to query or search existing insights (use `posthog-exploring-data` instead)
- The user wants to add insights to a dashboard (use `upsert-dashboard` instead)

## Insight Plan File Format

Insight plan YAML files are stored at `.posthog/insights/{short_id}-{slug}.yaml`

### Structure

```yaml
# PostHog Insight Plan
_meta:
  type: insight_plan
  insight_type: trends # trends | funnel | retention

name: 'Weekly Active Users'
description: 'Users with any event in last 7 days'

plan: |
  Series:
  - series 1: $pageview
      - math operation: unique users

  Time period: last 7 days
  Time interval: day
```

### Fields

| Field                | Description                                   |
| -------------------- | --------------------------------------------- |
| `_meta`              | Metadata including insight type               |
| `_meta.insight_type` | One of: `trends`, `funnel`, `retention`       |
| `name`               | Short, concise name (2-7 words)               |
| `description`        | Brief description of what the insight shows   |
| `plan`               | Structured plan following the type guidelines |

## Selecting an Insight Type

### Trends

Use for visualizing events over time. See [references/trends.md](references/trends.md) for full guidelines.

### Funnel

Use for visualizing a sequence of events. **Requires at least two events**. See [references/funnel.md](references/funnel.md) for full guidelines.

### Retention

Use for measuring how many users return. See [references/retention.md](references/retention.md) for full guidelines.

## Data Narrowing

### Property Filters

Use property filters to provide narrowed results. Only include property filters when they are essential to directly answer the user's question. Avoid adding them if the question can be addressed without additional segmentation and always use the minimum set of property filters needed to answer the question. Properties have one of the four types: String, Numeric, Boolean, and DateTime.

IMPORTANT: Do not check if a property is set unless the user explicitly asks for it.

When using a property filter, you must:

- **Prioritize properties directly related to the context or objective of the user's query.** Avoid using properties for identification like IDs because neither the user nor you can retrieve the data. Instead, prioritize filtering based on general properties like `paidCustomer` or `icp_score`.
- **Ensure that you find both the property group and name.** Property groups must be one of the following: event, person, session.
- After selecting a property, **validate that the property value accurately reflects the intended criteria**.
- **Find the suitable operator for type** (e.g., `contains`, `is set`). The operators are listed below.
- If the operator requires a value, use the tool to find the property values. Verify that you can answer the question with given property values. If you can't, try to find a different property or event.
- You set logical operators to combine multiple properties of a single series: AND or OR.

Infer the property groups from the user's request. If your first guess doesn't yield any results, try to adjust the property group. You must make sure that the property name matches the lookup value, e.g. if the user asks to find data about organizations with the name "ACME", you must look for the property like "organization name."

#### String Operators

- equals (exact)
- doesn't equal (is_not)
- contains (icontains)
- doesn't contain (not_icontains)
- matches regex (regex)
- doesn't match regex (not_regex)
- is set
- is not set

#### Numeric Operators

- equals (exact)
- doesn't equal (is_not)
- greater than (gt)
- less than (lt)
- is set
- is not set

#### DateTime Operators

- equals (is_date_exact)
- doesn't equal (is_not for existence check)
- before (is_date_before)
- after (is_date_after)
- is set
- is not set

#### Boolean Operators

- equals
- doesn't equal
- is set
- is not set

All operators take a single value except for `equals` and `doesn't equal` which can take one or more values (as an array).

### Time Period

You must not filter events by time, so you must not look for time-related properties. Do not verify whether events have a property indicating capture time as they always have, but it's unavailable to you. Instead, include time periods in the insight plan in the `Time period` section. If the question doesn't mention time, use `last 30 days` as a default time period.

Examples:

- If the user asks you "find events that happened between March 1st, 2025, and 2025-03-07", you must include `Time period: from 2025-03-01 to 2025-03-07` in the insight plan.
- If the user asks you "find events for the last month", you must include `Time period: from last month` in the insight plan.

## Reminders

- Ensure that any properties included are directly relevant to the context and objectives of the user's question. Avoid unnecessary or unrelated details.
- Avoid overcomplicating the response with excessive property filters. Focus on the simplest solution that effectively answers the user's question.
- When using group aggregations (unique groups), always set `math_group_type_index` to the appropriate group type index from the group mapping.
- Custom names for series or steps are optional and should only be used when the user explicitly wants to rename them or when the default name would be unclear.
- Visualization settings (display type, axis format, etc.) should only be specified when explicitly requested or when they significantly improve the answer to the user's question.
- The default funnel step order is `ordered` (events in sequence but with other events allowed in between). Use `strict` when events must happen consecutively with no events in between. Use `unordered` when order doesn't matter.
- Exclusion events in funnels only exclude conversions where the event happened between the specified steps, not before or after the funnel.

CRITICAL: When planning an insight, be minimalist. Only include filters, breakdowns, and settings that are essential to answer the user's specific question. Default settings are usually sufficient unless the user explicitly requests customization.

## Workflow

1. **Identify the insight type** based on what the user wants to know
2. **Read the appropriate reference file** for detailed guidelines:
   - [references/trends.md](references/trends.md) for trends insights
   - [references/funnel.md](references/funnel.md) for funnel insights
   - [references/retention.md](references/retention.md) for retention insights
3. **Determine the events/actions** needed from the user's project
4. **Write the plan** using the appropriate template from the reference
5. **Keep it minimal**: Only include what's necessary to answer the question
6. **Save to** `.posthog/insights/{short_id}-{slug}.yaml`

When creating the file:

- Generate an 8-character alphanumeric short_id (e.g., `abc123XY`)
- Create a slug from the name (lowercase, hyphens, no special chars)
- Use the filename format: `{short_id}-{slug}.yaml`
