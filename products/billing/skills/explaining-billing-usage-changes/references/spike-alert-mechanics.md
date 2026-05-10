# Usage alert mechanics

This reference explains how billing usage spike, drop, and change alerts are generated
and how to interpret a usage dashboard link that came from an alert email.

## What the email link gives you

The email CTA opens the organization usage dashboard with alert-relevant filters. The
URL has this shape:

```text
/organization/billing/usage?usage_types=["event_count_in_period"]&date_from=2023-12-16&date_to=2024-01-14&interval=day
```

- `usage_types` is a JSON array of billing usage type identifiers.
- `date_to` is the alert day, shown at the right edge of the chart.
- `date_from` is usually about 29 days before the alert day.
- `interval=day` matches the detector's daily usage reports.

The usage dashboard identifiers are the frontend/API usage type values, not always the
same short keys used by the detector internals.

PostHog AI side-panel prompts can be opened with a URL hash. The internal side-panel
route still uses `max`:

- `#panel=max:<prompt>` opens PostHog AI with the prompt prefilled.
- `#panel=max:!<prompt>` opens PostHog AI and auto-runs the prompt.

## How the detector decides

The billing service checks for spikes shortly after a usage report is saved.

- Only paid customers are considered.
- The detector uses recent daily usage history, with 16 days preferred and 7 days as
  the minimum.
- It skips metrics where more than half of the historical values are zero.
- It normalizes the latest value against separate weekday and weekend averages.
- It detects both increases and decreases.
- It uses a z-score threshold for variable series.
- If historical standard deviation is zero, it falls back to a relative change check.
- A 7-day cooldown avoids repeated alerts for the same metric.
- Warehouse rows synced are skipped by the detector.

Because the MCP usage endpoint exposes the usage series rather than the saved detector
row, an agent usually reconstructs the alert from the chart data. Say "best
reconstruction" when exact detector fields like z-score or relative change are not
available.

## Minimum average thresholds

The detector ignores very small accounts or metrics where tiny absolute changes would
look dramatic.

| Detector metric key       | Minimum historical average |
| ------------------------- | -------------------------- |
| `events`                  | 150,000                    |
| `enhanced_persons_events` | 150,000                    |
| `recordings`              | 7,000                      |
| `mobile_recordings`       | 7,000                      |
| `feature_flag_requests`   | 310,000                    |
| `exceptions`              | 100,000                    |
| other metrics             | 50,000                     |
| `rows_synced`             | skipped                    |

## Common usage type mapping

Use this mapping to translate usage dashboard filters into detector-oriented labels.
If the billing usage response returns a clearer label, prefer that response over this
table.

| Usage dashboard value                            | Detector key              | Human label                         |
| ------------------------------------------------ | ------------------------- | ----------------------------------- |
| `event_count_in_period`                          | `events`                  | Events                              |
| `enhanced_persons_event_count_in_period`         | `enhanced_persons_events` | Identified events                   |
| `recording_count_in_period`                      | `recordings`              | Recordings                          |
| `mobile_recording_count_in_period`               | `mobile_recordings`       | Mobile recordings                   |
| `billable_feature_flag_requests_count_in_period` | `feature_flag_requests`   | Feature flag requests               |
| `exceptions_captured_in_period`                  | `exceptions`              | Exceptions                          |
| `survey_responses_count_in_period`               | `survey_responses`        | Survey responses                    |
| `ai_event_count_in_period`                       | `llm_events`              | LLM events                          |
| `ai_credits_used_in_period`                      | `ai_credits`              | AI credits                          |
| `rows_exported_in_period`                        | `rows_exported`           | Rows exported                       |
| `cdp_billable_invocations_in_period`             | `cdp_trigger_events`      | Realtime destination trigger events |
| `workflow_emails_sent_in_period`                 | `workflow_emails`         | Workflow emails                     |
| `workflow_billable_invocations_in_period`        | `workflow_destinations`   | Workflow destinations               |
| `logs_mb_in_period`                              | `logs_mb_ingested`        | Logs MB ingested                    |

Data warehouse sync rows can appear under several billing usage keys. Do not force a
detector mapping for warehouse usage unless the billing response confirms the series.
