// A known-good STARTER scaffold for a freeform (React) canvas. Instead of
// authoring the whole single-file app from scratch every time, the generation
// path seeds this working baseline as the agent's starting point (on by default;
// opt out via the generate bar toggle). It already wires the pieces that are
// easy to get wrong — the date picker (self-sizing, no `compact`), theme-aware
// tokens, per-card loading skeletons, and reading a TYPED-NODE result correctly
// — so the agent edits a compiling app instead of re-deriving boilerplate.
//
// Stored as a string (like the prompt contracts) — it is injected into the
// generation prompt, not compiled here. It imports ONLY whitelisted packages
// (see freeformWhitelist) and uses the runtime `ph` global for data. The sample
// metric is "all events" (math:total, event:null) so it renders on ANY project;
// the agent replaces it with the user's real metrics.
export const FREEFORM_STARTER_CODE = `import React, { useEffect, useState } from "react";
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
} from "@posthog/quill";
import { RefreshCw } from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Starter scaffold. Replace the sample "total events" metric and the layout
// with what the user asked for — but KEEP the wiring below (date picker, theme
// tokens, skeletons, typed-node result reading), it is already correct.
export default function Canvas() {
  const def =
    quickRanges.find((r) => r.name === "Last 30 days") ?? quickRanges[0];
  const [win, setWin] = useState({
    start: def.rangeSetter(new Date()),
    end: new Date(),
    range: def,
  });
  const [open, setOpen] = useState(false);

  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);
  const [series, setSeries] = useState([]);
  // Refresh plumbing: bump this nonce to re-run the data effect on demand. The
  // effect already re-runs when the date window changes; the Refresh button just
  // forces a re-run with the same window.
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // PREFERRED data path: a TYPED query node, computed by PostHog's own runner
    // so the numbers match the UI exactly. \`event: null\` = all events (works on
    // any project). Swap in the real metric — ideally a SAVED insight loaded
    // with \`ph.loadInsight(shortId, { dateRange })\`.
    ph.query({
      kind: "TrendsQuery",
      series: [
        { kind: "EventsNode", event: null, name: "All events", math: "total" },
      ],
      dateRange: {
        date_from: win.start.toISOString(),
        date_to: win.end.toISOString(),
      },
    })
      .then((res) => {
        if (cancelled) return;
        // Typed-node result: \`results\` is an array of SERIES OBJECTS, not rows.
        const s = res.results[0] ?? {};
        setTotal(s.count ?? 0);
        setSeries(
          (s.days ?? []).map((day, i) => ({ day, value: s.data?.[i] ?? 0 })),
        );
        setLoading(false);
      })
      .catch(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [win, nonce]);

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex items-center justify-between">
        <Heading size="xl" className="mb-4">Canvas</Heading>
        <div className="flex items-center gap-2">
          <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
              render={<Button variant="outline">{win.range.name}</Button>}
            />
            {/* PopoverContent needs w-auto p-0 so its default fixed width +
                padding don't squeeze the self-sizing picker (which clips the
                quick-range tabs). No other styles on it or the picker. */}
            <PopoverContent className="w-auto p-0">
              <DateTimePicker
                value={win}
                onApply={(v) => {
                  setWin(v);
                  setOpen(false);
                }}
                onCancel={() => setOpen(false)}
              />
            </PopoverContent>
          </Popover>
          <Button
            variant="outline"
            disabled={loading}
            onClick={() => setNonce((n) => n + 1)}
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : undefined} />
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
                  <CartesianGrid
                    stroke="var(--border)"
                    strokeDasharray="3 3"
                  />
                  <XAxis
                    dataKey="day"
                    stroke="var(--muted-foreground)"
                    tick={{ fontSize: 12 }}
                  />
                  <YAxis
                    stroke="var(--muted-foreground)"
                    tick={{ fontSize: 12 }}
                  />
                  <Tooltip />
                  <Line
                    type="monotone"
                    dataKey="value"
                    stroke="var(--primary)"
                    dot={false}
                    strokeWidth={2}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
`;
