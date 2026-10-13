# Managed warehouse billing usage

## Dependency and rollout

The logical scan consumer builds on the managed warehouse usage puller in [PostHog/posthog#69494](https://github.com/PostHog/posthog/pull/69494).
Merge that puller before this addition.
Deploy the mirror migration before enabling the updated worker.
The billing service must register `managed_warehouse_logical_bytes_scanned` and its report counter `managed_warehouse_logical_bytes_scanned_in_period` before exposing the new metric.
This change does not add pricing, rounding, minimum charges, or free allowances.

## Pull contract

The consumer preserves `GET /api/v1/billing/usage` and `POST /api/v1/billing/ack`.
Requests use the existing `X-Duckgres-Internal-Secret` authentication header.
Both requests add `X-Hogtower-Billing-Metrics: logical_bytes_scanned`.
The producer must exclude logical scans from both export claims and acknowledgements when this capability is absent.
Storage continues to use the existing pull contract.

The response keeps `watermark_low`, `watermark_high`, `usage`, and `storage`.
The additive `scans` list contains one complete daily snapshot per `(org_id, team_id, query_source, date)`:

```json
{
  "date": "2026-07-06",
  "org_id": "018f0000-0000-0000-0000-000000000000",
  "team_id": 42,
  "query_source": "standard",
  "logical_bytes_scanned": 9007199254740993
}
```

An absent `scans` field is an older producer and decodes as an empty list.
A present non-list field or an unreadable row withholds the shared acknowledgement.
Logical byte counts must be JSON integers, never floating-point values or strings.
The mirror preserves up to 38 decimal digits and the usage report emits the exact integer without converting to TiB.
The raw report counter sums all query sources into one metric.
The mirror keeps the source dimension for inspection; endpoint queries do not receive a separate metric or tariff.

## Closed-day snapshots and acknowledgement

For the closed-day producer, `watermark_high` is the start of the current UTC day.
The response includes only billing accounting days before that boundary.
The consumer acknowledges `watermark_high - 1 second`, preserving the puller's existing day-boundary rule.
For example, a high watermark of `2026-07-07T00:00:00Z` acknowledges `2026-07-06T23:59:59Z`.
The producer must accept that acknowledgement even though it differs from the returned high watermark.
It must never truncate a daily snapshot by event count or include the current accounting day.

All metric families commit in the mirror transaction before the workflow sends the acknowledgement.
Repeated pulls replace daily totals instead of incrementing them.
A lower or omitted org/day logical-byte total retains the last trusted snapshot and withholds the acknowledgement.
The cursor rejects stale responses before they can replace a newer snapshot.

## Occurrence date and billing recognition date

Billing accounting dates follow receipt and recognition, not necessarily query completion.
A late completion retains its original completion and receipt timestamps in the source ledger.
Its billing recognition day is the current open UTC day if its original receipt day is already acknowledged.
The producer applies the same normalization to scans retained while the consumer lacked the logical-byte capability.
Those scans become eligible only after the newly assigned accounting day closes.

This avoids sending a late remainder as though it were a full historical-day snapshot.
Raw occurrence-date usage in the warehouse UI can therefore differ from billing-recognition daily totals, particularly across midnight or a month boundary.
The billing mirror does not rewrite an acknowledged day or recompute prices.
