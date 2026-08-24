# Canvas starter scaffold

A known-good baseline for a React + Quill data canvas. It already wires the pieces that are easy
to get wrong — the date picker (self-sizing, no `compact`), theme-aware tokens, per-query loading
state so every card fills in the moment its own data lands, reading a typed-node result correctly,
and the "View query" verification dialog every ad-hoc data card must carry. Start from it on a
first build: keep the wiring, replace the sample metrics and the layout with what the user asked
for. Ideally swap the inline `ph.query` typed nodes for saved insights loaded with
`ph.loadInsight(shortId, { dateRange })` (see the `querying-canvas-data` skill) — then replace the
"View query" dialog with a "View in PostHog" button calling `ph.openExternal(insightUrl)`, the URL
minted at authoring time by the `generate-app-url` MCP tool (`/insights/{id}`), so viewers verify
the numbers on the real insight with their own permissions applied.

The load-bearing pattern is `useCanvasQuery`: one instance per query, each owning its
`{ loading, error, data }`. All queries start concurrently on mount and each card renders as soon
as its own result arrives — a slow query only holds back its own card. Keep that shape as you add
metrics; never collapse the queries behind one shared `loading` flag or a `Promise.all`.

```tsx
import React, { useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DateTimePicker,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Heading,
  Popover,
  PopoverContent,
  PopoverTrigger,
  quickRanges,
  SkeletonText,
} from '@posthog/quill'
import { RefreshCw } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

// One builder per query feeds both the ph.query call and its "View query"
// dialog, so the query a viewer inspects is exactly the one that ran. Typed
// query nodes are computed by PostHog's own runner so the numbers match the
// UI exactly. `event: null` = all events (works on any project).
const totalEventsQuery = (dateRange) => ({
  kind: 'TrendsQuery',
  series: [{ kind: 'EventsNode', event: null, name: 'All events', math: 'total' }],
  dateRange,
})

// BoldNumber makes the runner compute uniques across the whole period;
// summing the per-day values (`count`) would recount anyone active on
// several days.
const uniqueUsersQuery = (dateRange) => ({
  kind: 'TrendsQuery',
  series: [{ kind: 'EventsNode', event: null, name: 'Unique users', math: 'dau' }],
  trendsFilter: { display: 'BoldNumber' },
  dateRange,
})

// One instance per query. Each section owns its own { loading, error, data }
// and renders the moment ITS result lands — never share one loading flag
// across queries or gate the canvas on Promise.all: that makes the fastest
// card wait for the slowest query.
function useCanvasQuery(runQuery, deps) {
  const [state, setState] = useState({ loading: true, error: null, data: null })
  useEffect(() => {
    let cancelled = false
    setState({ loading: true, error: null, data: null })
    runQuery()
      .then((data) => {
        if (cancelled) return
        setState({ loading: false, error: null, data })
      })
      .catch((err) => {
        if (cancelled) return
        // A failed query must LOOK failed — falling through to zeros or an
        // empty chart reads as "no data" and hides real breakage.
        setState({ loading: false, error: String(err?.message ?? err), data: null })
      })
    return () => {
      cancelled = true
    }
  }, deps)
  return state
}

function CardError({ message, onRetry }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <p className="text-sm text-destructive">Couldn't load: {message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        Retry
      </Button>
    </div>
  )
}

// Every ad-hoc ph.query card carries a verification affordance showing the
// exact query that ran. A card backed by a saved insight instead renders a
// "View in PostHog" Button calling ph.openExternal(insightUrl) — the URL
// minted by the generate-app-url MCP tool, never hand-built.
function ViewQueryDialog({ query }) {
  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm">
            View query
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Query behind this figure</DialogTitle>
        </DialogHeader>
        <div className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 font-mono text-xs">
          {JSON.stringify(query, null, 2)}
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function Canvas() {
  const def = quickRanges.find((r) => r.name === 'Last 30 days') ?? quickRanges[0]
  const [win, setWin] = useState({
    start: def.rangeSetter(new Date()),
    end: new Date(),
    range: def,
  })
  const [open, setOpen] = useState(false)
  // Refresh plumbing: bump this nonce to re-run every data effect on demand.
  const [nonce, setNonce] = useState(0)
  const retry = () => setNonce((n) => n + 1)

  const dateRange = {
    date_from: win.start.toISOString(),
    date_to: win.end.toISOString(),
  }

  // Both queries fire concurrently on mount; the cards below fill in
  // independently as each result arrives.
  const events = useCanvasQuery(
    () =>
      ph.query(totalEventsQuery(dateRange)).then((res) => {
        // Typed-node result: `results` is an array of SERIES OBJECTS, not rows.
        const firstSeries = res.results[0] ?? {}
        return {
          total: firstSeries.count ?? 0,
          series: (firstSeries.days ?? []).map((day, index) => ({
            day,
            value: firstSeries.data?.[index] ?? 0,
          })),
        }
      }),
    [win, nonce]
  )
  const visitors = useCanvasQuery(
    () => ph.query(uniqueUsersQuery(dateRange)).then((res) => res.results[0]?.aggregated_value ?? 0),
    [win, nonce]
  )
  const anyLoading = events.loading || visitors.loading

  return (
    // The canvas root must resolve height against the iframe viewport. The
    // chrome (heading, date picker, card frames) renders immediately — only
    // the value inside each card waits, each for its own query.
    <div className="flex h-screen flex-col gap-4 overflow-y-auto p-6">
      <div className="flex items-center justify-between">
        <Heading size="xl" className="mb-4">
          Canvas
        </Heading>
        <div className="flex items-center gap-2">
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger render={<Button variant="outline">{win.range.name}</Button>} />
            {/* PopoverContent needs w-auto p-0 so its default fixed width +
                padding don't squeeze the self-sizing picker (which clips the
                quick-range tabs). No other styles on it or the picker. */}
            <PopoverContent className="w-auto p-0">
              <DateTimePicker
                value={win}
                onApply={(v) => {
                  setWin(v)
                  setOpen(false)
                }}
                onCancel={() => setOpen(false)}
              />
            </PopoverContent>
          </Popover>
          <Button variant="outline" disabled={anyLoading} onClick={retry}>
            <RefreshCw size={14} className={anyLoading ? 'animate-spin' : undefined} />
            Refresh
          </Button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card size="sm">
          <CardHeader>
            <CardTitle>Total events</CardTitle>
          </CardHeader>
          <CardContent>
            {events.loading ? (
              <SkeletonText lines={1} className="text-3xl" />
            ) : events.error ? (
              <CardError message={events.error} onRetry={retry} />
            ) : (
              <Heading size="2xl">{events.data.total.toLocaleString()}</Heading>
            )}
          </CardContent>
        </Card>
        <Card size="sm">
          <CardHeader>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Unique users</CardTitle>
              <ViewQueryDialog query={uniqueUsersQuery(dateRange)} />
            </div>
          </CardHeader>
          <CardContent>
            {visitors.loading ? (
              <SkeletonText lines={1} className="text-3xl" />
            ) : visitors.error ? (
              <CardError message={visitors.error} onRetry={retry} />
            ) : (
              <Heading size="2xl">{visitors.data.toLocaleString()}</Heading>
            )}
          </CardContent>
        </Card>
      </div>

      <Card size="sm">
        <CardHeader>
          <div className="flex items-center justify-between gap-2">
            <CardTitle>Events over time</CardTitle>
            <ViewQueryDialog query={totalEventsQuery(dateRange)} />
          </div>
        </CardHeader>
        <CardContent>
          {events.loading ? (
            <SkeletonText lines={6} />
          ) : events.error ? (
            <CardError message={events.error} onRetry={retry} />
          ) : (
            <div className="h-[280px] w-full">
              <ResponsiveContainer>
                <LineChart data={events.data.series}>
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                  <XAxis dataKey="day" stroke="var(--muted-foreground)" tick={{ fontSize: 12 }} />
                  <YAxis stroke="var(--muted-foreground)" tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Line type="monotone" dataKey="value" stroke="var(--primary)" dot={false} strokeWidth={2} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
```

Note: `ph` is a global the host injects into the sandbox (`window.ph`) — do not import it, and do
not import or initialize posthog-js.
