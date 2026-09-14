# Metric catalog

The catalog first requests metric names and types from `metrics/names/`.
It does not read metric values until a card is near the visible area.

Visible cards enter a shared queue.
After 50 ms, the queue sends up to 20 exact names to `metrics/values/` in one request.
Only one batch runs at a time.
The request uses POST with a JSON `names` array and keeps the current service filter.
The server ignores `value` and `limit` when `names` is present.
It returns up to 24 recent sparkline points per metric.

The catalog matches responses by metric name, not response order.
A service change clears queued cards and makes old responses invalid, including errors.
Failed cards keep the Retry button.
Query budget failures return an error instead of partial results.
The catalog shows the empty state only after a successful request returns no usable points.

Each sparkline needs an explicit width and height.
The card gives the shared `Sparkline` component `w-full h-full` inside a fixed-height container.

## Tests

The component tests check the POST batch after the queue delay.
The Storybook tests use an explicit container width and wait for a visible chart.
They do not wait for every loading placeholder to disappear: offscreen cards stay unloaded until they enter view.
