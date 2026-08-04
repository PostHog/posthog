# Canvas starter scaffold

A known-good baseline for a React + Quill data canvas. It already wires the pieces that are easy
to get wrong — the date picker (self-sizing, no `compact`), theme-aware tokens, per-card loading
skeletons, and reading a typed-node result correctly. Start from it on a first build: keep the
wiring, replace the sample "total events" metric and the layout with what the user asked for.
Ideally swap the inline `ph.query` typed node for a saved insight loaded with
`ph.loadInsight(shortId, { dateRange })` (see the `querying-canvas-data` skill).

```tsx
import React, { useEffect, useState } from 'react'
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DateTimePicker,
  Heading,
  Popover,
  PopoverContent,
  PopoverTrigger,
  quickRanges,
  SkeletonText,
} from '@posthog/quill'
import { RefreshCw } from 'lucide-react'
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export default function Canvas() {
  const def = quickRanges.find((r) => r.name === 'Last 30 days') ?? quickRanges[0]
  const [win, setWin] = useState({
    start: def.rangeSetter(new Date()),
    end: new Date(),
    range: def,
  })
  const [open, setOpen] = useState(false)

  const [loading, setLoading] = useState(true)
  const [total, setTotal] = useState(0)
  const [series, setSeries] = useState([])
  // Refresh plumbing: bump this nonce to re-run the data effect on demand.
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    // Typed query node, computed by PostHog's own runner so the numbers match
    // the UI exactly. `event: null` = all events (works on any project).
    ph.query({
      kind: 'TrendsQuery',
      series: [{ kind: 'EventsNode', event: null, name: 'All events', math: 'total' }],
      dateRange: {
        date_from: win.start.toISOString(),
        date_to: win.end.toISOString(),
      },
    })
      .then((res) => {
        if (cancelled) return
        // Typed-node result: `results` is an array of SERIES OBJECTS, not rows.
        const s = res.results[0] ?? {}
        setTotal(s.count ?? 0)
        setSeries((s.days ?? []).map((day, i) => ({ day, value: s.data?.[i] ?? 0 })))
        setLoading(false)
      })
      .catch((error) => {
        if (!cancelled) setLoading(false)
        throw error
      })
    return () => {
      cancelled = true
    }
  }, [win, nonce])

  return (
    <div className="flex flex-col gap-4 p-6">
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
          <Button variant="outline" disabled={loading} onClick={() => setNonce((n) => n + 1)}>
            <RefreshCw size={14} className={loading ? 'animate-spin' : undefined} />
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
            {loading ? (
              <SkeletonText lines={1} className="text-3xl" />
            ) : (
              <Heading size="2xl">{total.toLocaleString()}</Heading>
            )}
          </CardContent>
        </Card>
      </div>

      <Card size="sm">
        <CardHeader>
          <CardTitle>Events over time</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <SkeletonText lines={6} />
          ) : (
            <div className="h-[280px] w-full">
              <ResponsiveContainer>
                <LineChart data={series}>
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
