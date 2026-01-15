# Funnel Guidelines

A funnel insight visualizes a sequence of events that users go through in a product. They use percentages as the primary aggregation type. Funnels REQUIRE AT LEAST TWO series (events or actions), so the conversation history should mention at least two events.

The funnel insights have the following features:

- Various visualization types (steps, time-to-convert, historical trends).
- Filter data and apply exclusion steps (events only, not actions).
- Break down data using a single property.
- Specify conversion windows (default 14 days), step order (strict/ordered/unordered), and attribution settings.
- Aggregate by users, sessions, or specific group types.
- Sample data.
- Track first-time conversions with special math aggregations.
- And more.

Examples of use cases include:

- Conversion rates between steps.
- Drop off steps (which step loses most users).
- Steps with the highest friction and time to convert.
- If product changes are improving their funnel over time.
- Average/median/histogram of time to convert.
- Conversion trends over time (using trends visualization type).
- First-time user conversions (using first_time_for_user math).

## General Knowledge

Funnel insights help stakeholders understand user behavior as users navigate through a product. A funnel consists of a sequence of at least two events or actions, where some users progress to the next step while others drop off. Funnels are perfect for finding conversion rates, average and median conversion time, conversion trends, and distribution of conversion time.

## Exclusion Steps

Users may want to use exclusion events to filter out conversions in which a particular event occurred between specific steps. These events must not be included in the main sequence. You must include start and end indexes for each exclusion where the minimum index is 1 (after first step) and the maximum index is the number of steps in the funnel. Exclusion events cannot be actions, only events.

IMPORTANT: Exclusion steps filter out conversions where the exclusion event occurred BETWEEN the specified steps. This does NOT exclude users who completed the event before the funnel started or after it ended.

For example, there is a sequence with three steps: sign up (step 1), finish onboarding (step 2), purchase (step 3). If the user wants to exclude all conversions in which users navigated away between sign up and finishing onboarding, the exclusion step will be:

```
Exclusions:
- $pageleave
    - start index: 1 (after sign up)
    - end index: 2 (before finish onboarding)
```

## Breakdown

A breakdown is used to segment data by a single property value. They divide all defined funnel series into multiple subseries based on the values of the property. Include a breakdown **only when it is essential to directly answer the user's question**. You must not add a breakdown if the question can be addressed without additional segmentation.

When using breakdowns, you must:

- **Identify the property group** and name for a breakdown.
- **Provide the property name** for a breakdown.
- **Validate that the property value accurately reflects the intended criteria**.

Examples of using a breakdown:

- page views to sign up funnel by country: you need to find a property such as `$geoip_country_code` and set it as a breakdown.
- conversion rate of users who have completed onboarding after signing up by an organization: you need to find a property such as `organization name` and set it as a breakdown.

## Reminders

- You MUST ALWAYS use AT LEAST TWO series (events or actions) in the funnel plan.

## Plan Template

```
Sequence:

1. event: event name 1
    - custom name: (optional) custom display name for this step
    - math operation: (optional) first_time_for_user or first_time_for_user_with_filters
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
2. action: action name 2
    - action id: `numeric id`
    - custom name: (optional) custom display name for this step
    - math operation: (optional) first_time_for_user or first_time_for_user_with_filters
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
3. Repeat for each event or action...

(if exclusion steps are used)
Exclusions:

- exclusion event name 1
    - start index: 1
    - end index: 2
- exclusion event name 2... Repeat for each exclusion...

(if a breakdown is used)
Breakdown by:

- entity
- property name

(if aggregating by groups instead of users)
Aggregate by: group type index from group mapping

(if a time period is explicitly mentioned)
Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.

(optional funnel settings)
Visualization type: steps/time_to_convert/trends
Conversion window: number and unit (e.g., 14 days, 1 hour)
Step order: strict/ordered/unordered
Step reference: total/previous (for conversion percentages)
Layout: vertical/horizontal
Bin count: (only for time_to_convert, number of histogram bins)
```
