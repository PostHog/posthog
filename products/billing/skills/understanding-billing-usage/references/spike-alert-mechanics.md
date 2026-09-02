# Usage alert links

Usage spike, drop, and change alert emails open the organization usage dashboard with
alert-relevant filters. The link usually has this shape:

```text
/organization/billing/usage?usage_types=["event_count_in_period"]&date_from=2023-12-16&date_to=2024-01-14&interval=day
```

- `usage_types` is a JSON array of billing usage type identifiers.
- `date_to` is the alert day, shown at the right edge of the chart.
- `date_from` is usually about 29 days before the alert day.
- `interval=day` matches the daily Billing usage series.

Use these URL parameters to recreate the Billing view first. Then drill into the
customer-visible product data for the affected usage type, project, and day.

When validating an alert day, compare it to prior days in the same day class:

- weekday alert day: compare to prior weekdays in the visible range
- weekend alert day: compare to prior weekend days in the visible range

This avoids treating normal weekday/weekend traffic shape as a root cause. Keep the
answer grounded in what the Billing usage tools return, and call it a reconstruction
when you do not have the exact alert row.
