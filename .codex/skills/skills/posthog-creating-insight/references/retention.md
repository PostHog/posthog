# Retention Guidelines

A retention insight visualizes how many users return to the product after performing some action. They're useful for understanding user engagement and retention.

The retention insights have the following features: filter data, sample data, and more.

Examples of use cases include:

- How many users come back and perform an action after their first visit.
- How many users come back to perform action X after performing action Y.
- How often users return to use a specific feature.

## General Knowledge

Retention is a type of insight that shows you how many users return during subsequent periods.

They're useful for answering questions like:

- Are new sign ups coming back to use your product after trying it?
- Have recent changes improved retention?

## Retention Plan

Plans of retention insights must always have two events or actions:

- The activation event – an event or action that determines if the user is a part of a cohort (when they "start").
- The retention event – an event or action that determines whether a user has been retained (when they "return").

For activation and retention events, use the `$pageview` event by default or the equivalent for mobile apps `$screen`. Avoid infrequent or inconsistent events like `signed in` unless asked explicitly, as they skew the data.

The activation and retention events can be the same (e.g., both `$pageview` to see if users who viewed pages come back to view pages again) or different (e.g., activation is `signed up` and retention is `completed purchase` to see if sign-ups convert to purchases over time).

## Plan Template

```
Activation:
(if an event is used)

- event: chosen event name
  (or if an action is used)
- action id: `numeric id`
- action name: action name

Retention:

- event: chosen event name (can be the same as activation event, or different)
  (or if an action is used)
- action id: `numeric id`
- action name: action name

(if filters are used)
Filters:
- property filter 1:
    - entity
    - property name
    - property type
    - operator
    - property value
- property filter 2... Repeat for each property filter.

(if a time period is explicitly mentioned)
Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.
```
