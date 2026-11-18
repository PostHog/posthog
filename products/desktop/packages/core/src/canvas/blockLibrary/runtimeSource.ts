export const BLOCK_RUNTIME_SOURCE = `import { type ReactNode, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ph } from "@posthog/canvas-sdk";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@posthog/quill";
import { CodeIcon } from "./icons";

export type CanvasInterval = "hour" | "day" | "week" | "month";

export type FilterOperator = "exact" | "is_not" | "icontains" | "not_icontains" | "is_set" | "is_not_set" | "gt" | "lt";

export type CanvasPropertyFilter = {
  key: string;
  value: string;
  type: "event" | "person";
  operator?: FilterOperator;
};

export type CanvasFilters = {
  dateFrom: string;
  interval: CanvasInterval;
  properties: CanvasPropertyFilter[];
  compare?: boolean;
};

export type BlockProps = {
  blockId?: string;
  sql?: string;
  span?: "wide" | "full";
  description?: string;
  "data-ph-src"?: string;
};

const FILTERS_KEY = "blocks.filters";
const DEFAULT_FILTERS: CanvasFilters = { dateFrom: "-30d", interval: "day", properties: [] };
const listeners = new Set<() => void>();
let filters: CanvasFilters = DEFAULT_FILTERS;
let loaded = false;
let saveTimer: ReturnType<typeof setTimeout> | undefined;

function emit() {
  for (const listener of listeners) listener();
}

function loadFilters() {
  if (loaded) return;
  loaded = true;
  Promise.resolve(ph.state.get(FILTERS_KEY, { scope: "user" }))
    .then((stored: unknown) => {
      if (!stored || typeof stored !== "object") return;
      filters = { ...DEFAULT_FILTERS, ...(stored as Partial<CanvasFilters>) };
      emit();
    })
    .catch(() => undefined);
}

export function setCanvasFilters(next: CanvasFilters) {
  filters = next;
  emit();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    Promise.resolve(ph.state.set(FILTERS_KEY, next, { scope: "user" })).catch(() => undefined);
  }, 400);
}

export function useCanvasFilters(): CanvasFilters {
  loadFilters();
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => filters,
  );
}

export type QueryResult = {
  columns: string[];
  results: any[];
  hogql?: string;
  insight?: { name: string | null; kind: string | null; display: string | null };
};

const MAX_PARALLEL_QUERIES = 6;
let runningQueries = 0;
const waitingQueries: Array<() => void> = [];

async function queued<T>(run: () => Promise<T>): Promise<T> {
  if (runningQueries >= MAX_PARALLEL_QUERIES) {
    await new Promise<void>((resolve) => waitingQueries.push(resolve));
  }
  runningQueries += 1;
  try {
    return await run();
  } finally {
    runningQueries -= 1;
    waitingQueries.shift()?.();
  }
}

async function withRetry(run: () => Promise<unknown>): Promise<QueryResult> {
  for (let attempt = 0; ; attempt += 1) {
    try {
      return (await queued(run)) as QueryResult;
    } catch (error) {
      const busy = String((error as Error)?.message ?? error).includes("runtime limits");
      if (!busy || attempt >= 3) throw error;
      await new Promise((resolve) => setTimeout(resolve, 300 * (attempt + 1)));
    }
  }
}

let refreshNonce = 0;
let lastUpdated: number | null = null;
const refreshListeners = new Set<() => void>();

function emitRefresh() {
  for (const listener of refreshListeners) listener();
}

function subscribeRefresh(listener: () => void) {
  refreshListeners.add(listener);
  return () => refreshListeners.delete(listener);
}

export function refreshCanvasData() {
  refreshNonce += 1;
  emitRefresh();
}

export function useRefreshNonce(): number {
  return useSyncExternalStore(subscribeRefresh, () => refreshNonce);
}

export function useLastUpdated(): number | null {
  return useSyncExternalStore(subscribeRefresh, () => lastUpdated);
}

function markUpdated() {
  lastUpdated = Date.now();
  emitRefresh();
}

const cache = new Map<string, Promise<QueryResult>>();
const resolved = new Map<string, QueryResult>();
const MAX_RESOLVED = 200;

function remember(key: string, data: QueryResult) {
  cache.delete(key);
  resolved.delete(key);
  resolved.set(key, data);
  while (resolved.size > MAX_RESOLVED) {
    const oldest = resolved.keys().next().value;
    if (oldest === undefined) break;
    resolved.delete(oldest);
  }
}

type RequestState = { data: QueryResult | null; error: string | null; loading: boolean };

function useCachedRequest(key: string | null, run: () => Promise<QueryResult>): RequestState {
  const [state, setState] = useState<RequestState>(() => ({
    data: key ? (resolved.get(key) ?? null) : null,
    error: null,
    loading: key !== null && !resolved.has(key),
  }));
  const latest = useRef(key);
  const runner = useRef(run);
  runner.current = run;
  useEffect(() => {
    latest.current = key;
    if (!key) return;
    const known = resolved.get(key);
    if (known) {
      setState({ data: known, error: null, loading: false });
      return;
    }
    setState((previous) => ({ ...previous, loading: true, error: null }));
    let request = cache.get(key);
    if (!request) {
      request = runner.current();
      cache.set(key, request);
      request.catch(() => cache.delete(key));
    }
    request
      .then((data) => {
        remember(key, data);
        markUpdated();
        if (latest.current === key) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (latest.current !== key) return;
        const message = error instanceof Error ? error.message : String(error);
        setState({ data: null, error: message, loading: false });
      });
  }, [key]);
  return state;
}

export function useBlockQuery(node: Record<string, unknown> | null, nonce = 0): RequestState {
  const refresh = useRefreshNonce();
  const key = node ? JSON.stringify(node) + "#" + nonce + "#" + refresh : null;
  return useCachedRequest(key, () => withRetry(() => Promise.resolve(ph.query(node as never))));
}

export function useBlockInsight(shortId: string | null, dateFrom: string | null): RequestState {
  const refresh = useRefreshNonce();
  const key = shortId ? "insight:" + shortId + "#" + (dateFrom ?? "saved") + "#" + refresh : null;
  return useCachedRequest(key, () =>
    withRetry(() => Promise.resolve(ph.loadInsight(shortId as string, dateFrom ? { dateRange: { date_from: dateFrom } } : {}))),
  );
}

type BlockRootOptions = {
  params?: Record<string, unknown>;
};

function serializableProps(props: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (key === "children" || key === "data-ph-src" || typeof value === "function") continue;
    if (value !== null && typeof value === "object" && !Array.isArray(value)) continue;
    result[key] = value;
  }
  return result;
}

export function blockRoot(type: string, props: BlockProps & Record<string, unknown>, options: BlockRootOptions = {}) {
  return {
    "data-ph-block": type,
    "data-ph-block-id": props.blockId,
    "data-ph-props": JSON.stringify(serializableProps(props)),
    "data-ph-src": props["data-ph-src"],
    "data-ph-params": options.params ? JSON.stringify(options.params) : undefined,
    style: props.span === "full" ? { gridColumn: "1 / -1" } : props.span === "wide" ? { gridColumn: "span 2" } : undefined,
  };
}

export function sqlNode(sql: string, filters: CanvasFilters, followFilters = true) {
  return { kind: "HogQLQuery", query: sql, filters: filterFields(filters, followFilters) };
}

export function eventsNode(event: string, math = "total") {
  return { kind: "EventsNode", event, name: event, math };
}

export function filterFields(filters: CanvasFilters, followFilters = true) {
  return {
    dateRange: { date_from: filters.dateFrom },
    properties: followFilters
      ? filters.properties.map((property) => {
          const operator = property.operator ?? "exact";
          const presence = operator === "is_set" || operator === "is_not_set";
          return { key: property.key, value: presence ? operator : property.value, operator, type: property.type };
        })
      : [],
  };
}

export const CHART_COLORS = ["#1d4aff", "#f54e00", "#43827e", "#a621c8", "#f1a82c"];

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const whole = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const shortDate = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "0";
  return Math.abs(value) < 10000 ? whole.format(value) : compact.format(value);
}

export function formatPercent(value: number): string {
  return (value >= 10 ? Math.round(value) : value.toFixed(1)) + "%";
}

const RANGE_DAYS: Record<string, number> = { "-24h": 1, "-7d": 7, "-14d": 14, "-30d": 30, "-90d": 90, "-180d": 180, "-365d": 365 };
const DAY_MS = 86400000;

export function fillDateRows(xs: string[], rows: unknown[][], dateFrom: string): { xs: string[]; rows: unknown[][] } {
  const isDate = xs.length > 1 && xs.every((x) => /^[0-9]{4}-[0-9]{2}-[0-9]{2}/.test(x));
  if (!isDate) return { xs, rows };
  const keys = xs.map((x) => x.slice(0, 10));
  const times = keys.map((key) => Date.parse(key + "T00:00:00Z"));
  const gaps = times.slice(1).map((time, index) => Math.round((time - times[index]) / DAY_MS)).filter((gap) => gap > 0);
  const step = Math.min(...gaps);
  if (step !== 1 && step !== 7) return { xs, rows };
  const byKey = new Map(keys.map((key, index) => [key, rows[index]]));
  const today = new Date();
  const end = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  const span = RANGE_DAYS[dateFrom];
  const start = span ? Math.min(times[0], end - span * DAY_MS) : times[0];
  const width = rows[0]?.length ?? 2;
  const filledXs: string[] = [];
  const filledRows: unknown[][] = [];
  const anchor = times[0];
  const first = anchor - Math.floor((anchor - start) / (step * DAY_MS)) * step * DAY_MS;
  for (let time = first; time <= end; time += step * DAY_MS) {
    const key = new Date(time).toISOString().slice(0, 10);
    filledXs.push(key);
    filledRows.push(byKey.get(key) ?? [key, ...Array.from({ length: width - 1 }, () => 0)]);
  }
  return { xs: filledXs, rows: filledRows };
}

export function previousSqlNode(sql: string, filters: CanvasFilters, followFilters = true) {
  const span = RANGE_DAYS[filters.dateFrom];
  if (!span || span < 7) return null;
  const node = sqlNode(sql, filters, followFilters);
  return { ...node, filters: { ...node.filters, dateRange: { date_from: "-" + span * 2 + "d", date_to: "-" + span + "d" } } };
}

export function previousRowsByDay(xs: string[], rows: unknown[][], dateFrom: string): Map<string, unknown[]> {
  const span = RANGE_DAYS[dateFrom] ?? 0;
  const times = xs.map((x) => Date.parse(x.slice(0, 10) + "T00:00:00Z"));
  const gaps = times.slice(1).map((time, index) => Math.round((time - times[index]) / DAY_MS)).filter((gap) => gap > 0);
  const step = gaps.length > 0 ? Math.min(...gaps) : 1;
  const shift = Math.round(span / step) * step * DAY_MS;
  const byDay = new Map<string, unknown[]>();
  times.forEach((time, index) => {
    if (!Number.isNaN(time)) byDay.set(new Date(time + shift).toISOString().slice(0, 10), rows[index]);
  });
  return byDay;
}

export function formatDay(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : shortDate.format(date);
}

export const DATE_RANGES = [
  { value: "-7d", label: "7D" },
  { value: "-30d", label: "30D" },
  { value: "-90d", label: "90D" },
  { value: "-180d", label: "6M" },
  { value: "-365d", label: "12M" },
];

export function rangeLabel(value: string): string {
  const labels: Record<string, string> = {
    "-24h": "Last 24 hours",
    "-7d": "Last 7 days",
    "-14d": "Last 14 days",
    "-30d": "Last 30 days",
    "-90d": "Last 90 days",
    "-180d": "Last 6 months",
    "-365d": "Last 12 months",
  };
  return labels[value] ?? value;
}

export function breakdownLabel(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Unknown";
  const text = String(value);
  if (text === "$$_posthog_breakdown_other_$$") return "Other";
  if (text === "$$_posthog_breakdown_null_$$") return "Unknown";
  if (text === "$direct") return "Direct";
  return text;
}

export const FILTER_OPERATORS: Array<{ value: FilterOperator; label: string }> = [
  { value: "exact", label: "is" },
  { value: "is_not", label: "is not" },
  { value: "icontains", label: "contains" },
  { value: "not_icontains", label: "does not contain" },
  { value: "is_set", label: "is set" },
  { value: "is_not_set", label: "is not set" },
];

export function propertyLabel(key: string): string {
  const known: Record<string, string> = {
    $browser: "Browser",
    $os: "OS",
    $device_type: "Device type",
    $current_url: "URL",
    $pathname: "Path",
    $referring_domain: "Referring domain",
    $geoip_country_name: "Country",
    $geoip_city_name: "City",
  };
  if (known[key]) return known[key];
  const text = key.replace(/^\\$/, "").replace(/[_-]+/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function filterLabel(filter: CanvasPropertyFilter): string {
  const operator = filter.operator ?? "exact";
  const verb = FILTER_OPERATORS.find((option) => option.value === operator)?.label ?? "is";
  const subject = (filter.type === "person" ? "Person " : "") + propertyLabel(filter.key);
  const presence = operator === "is_set" || operator === "is_not_set";
  return presence ? subject + " " + verb : subject + " " + verb + " " + filter.value;
}

export function scopeLabel(filters: CanvasFilters, followFilters = true): string {
  const values = followFilters
    ? filters.properties.map((property) => ((property.operator ?? "exact") === "exact" ? String(property.value) : filterLabel(property)))
    : [];
  return [rangeLabel(filters.dateFrom), ...values].join(" · ");
}

export function eventName(event: string): string {
  const known: Record<string, string> = { $pageview: "Pageview", $autocapture: "Autocapture", $pageleave: "Pageleave", $web_vitals: "Web vitals", $feature_flag_called: "Feature flag called", $groupidentify: "Group identify", $set: "Set person properties" };
  if (known[event]) return known[event];
  if (!event.startsWith("$")) return event;
  const words = event.slice(1).split("_").join(" ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function changeTone(value: number): string {
  if (Math.abs(value) < 0.05) return "bg-muted text-muted-foreground";
  return value > 0 ? "bg-emerald-500/10 text-emerald-600" : "bg-red-500/10 text-red-600";
}

export function ChangeBadge({ value }: { value: number }) {
  return (
    <span className={"rounded-full px-1.5 py-0.5 text-xs font-medium tabular-nums " + changeTone(value)} title="Change from the previous period">
      {(value > 0 ? "+" : "") + formatPercent(value)}
    </span>
  );
}

const MATH_LABELS: Record<string, string> = {
  total: "Count of",
  dau: "Unique users who did",
  weekly_active: "Weekly active users who did",
  monthly_active: "Monthly active users who did",
};

type QueryNode = {
  kind?: string;
  query?: string;
  series?: Array<{ event?: string; math?: string }>;
  interval?: string;
  dateRange?: { date_from?: string };
  compareFilter?: { compare?: boolean };
  breakdownFilter?: { breakdown?: string };
  trendsFilter?: { display?: string };
  properties?: Array<{ key?: string; value?: unknown; type?: string; operator?: string }>;
};

export function summarizeQuery(query: unknown): string {
  const node = (query ?? {}) as QueryNode;
  if (node.kind === "HogQLQuery") return "A custom HogQL query.";
  const series = (node.series ?? [])
    .map((item) => (MATH_LABELS[item.math ?? "total"] ?? "Count of") + " " + eventName(item.event ?? "events"))
    .join(" and ");
  const parts = [series || "Events"];
  if (node.breakdownFilter?.breakdown) parts.push("broken down by " + node.breakdownFilter.breakdown);
  const single = node.trendsFilter?.display === "BoldNumber" || node.trendsFilter?.display === "ActionsTable";
  if (!single && node.interval) parts.push("per " + node.interval);
  if (node.dateRange?.date_from) parts.push(rangeLabel(node.dateRange.date_from).toLowerCase());
  if (node.compareFilter?.compare) parts.push("compared with the previous period");
  const filters = (node.properties ?? []).map((item) =>
    filterLabel({
      key: String(item.key),
      value: String(item.value),
      type: item.type === "person" ? "person" : "event",
      operator: item.operator as FilterOperator | undefined,
    }),
  );
  if (filters.length > 0) parts.push("where " + filters.join(" and "));
  return parts.join(", ") + ".";
}

export function QueryButton({ query, hogql, className = "" }: { query: unknown; hogql?: string; className?: string }) {
  const node = (query ?? {}) as QueryNode;
  const inline = node.kind === "HogQLQuery" && node.query ? node.query : null;
  const text = inline ?? hogql ?? JSON.stringify(query, null, 2);
  const isSql = inline !== null || !!hogql;
  return (
    <span className={className + " opacity-0 transition-opacity group-hover:opacity-100"}>
    <Dialog>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm" aria-label="Show query">
            <CodeIcon className="size-3.5" />
          </Button>
        }
      />
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Query behind this block</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 px-4 pb-4">
          <p className="text-sm">{summarizeQuery(query)}</p>
          <pre className="max-h-[50vh] overflow-auto rounded-md bg-muted p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words">{text}</pre>
          <p className="text-xs text-muted-foreground">
            {isSql ? "This HogQL runs with your access each time the canvas loads." : "The query definition. It runs with your access each time the canvas loads."}
          </p>
        </div>
      </DialogContent>
    </Dialog>
    </span>
  );
}

function tableCell(value: unknown): string {
  if (value === null || value === undefined) return "null";
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

export function ResultTable({ columns, rows }: { columns: string[]; rows: unknown[] }) {
  return (
    <div className="max-h-80 overflow-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} className="border-b border-border py-1.5 pr-3 text-left text-xs font-normal text-muted-foreground">{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 100).map((row, rowIndex) => {
            const cells = Array.isArray(row) ? row : [row];
            return (
              <tr key={rowIndex} className="border-b border-border last:border-b-0">
                {columns.map((column, columnIndex) => (
                  <td key={column} className="max-w-60 truncate py-1.5 pr-3 tabular-nums">{tableCell(cells[columnIndex])}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function isPreviewDenial(error: string): boolean {
  return error.includes("capability manifest is unavailable") || error.includes("preview has no data access");
}

export function BlockState({ loading, error, empty, height = 160, children }: {
  loading: boolean;
  error: string | null;
  empty: boolean;
  height?: number;
  children: ReactNode;
}) {
  if (error && isPreviewDenial(error)) {
    return <div className="rounded-md bg-muted/60" style={{ height }} />;
  }
  if (error) {
    return (
      <div className="flex flex-col items-center justify-center gap-1 rounded-md bg-muted/40 px-4 text-center" style={{ minHeight: height }}>
        <span className="text-sm text-foreground">Couldn't load this data</span>
        <span className="line-clamp-2 text-xs text-muted-foreground">{error}</span>
      </div>
    );
  }
  if (loading && empty) {
    return <div className="animate-pulse rounded-md bg-muted/60" style={{ height }} />;
  }
  if (empty) {
    return (
      <div className="flex items-center justify-center rounded-md bg-muted/40 text-sm text-muted-foreground" style={{ minHeight: height }}>
        No data for this range
      </div>
    );
  }
  return <div className={loading ? "opacity-60 transition-opacity" : "transition-opacity"}>{children}</div>;
}

export type RetentionCohort = { date?: string; label?: string; values?: Array<{ count?: number }> };

export function RetentionGrid({ cohorts, period }: { cohorts: RetentionCohort[]; period: string }) {
  const columns = Math.max(0, ...cohorts.map((cohort) => cohort.values?.length ?? 0));
  const unit = period.toLowerCase();
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr className="text-muted-foreground">
            <th colSpan={2} />
            <th colSpan={columns} className="pb-0.5 text-left font-normal">{unit.charAt(0).toUpperCase() + unit.slice(1)}s later</th>
          </tr>
          <tr className="text-muted-foreground">
            <th className="py-1 pr-3 text-left font-normal">Cohort</th>
            <th className="py-1 pr-3 text-right font-normal">People</th>
            {Array.from({ length: columns }, (_, index) => (
              <th key={index} className="min-w-9 py-1 text-center font-normal tabular-nums">
                {index}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cohorts.map((cohort, row) => {
            const size = Number(cohort.values?.[0]?.count ?? 0);
            return (
              <tr key={(cohort.date ?? cohort.label ?? "") + row}>
                <td className="whitespace-nowrap py-1 pr-3 text-muted-foreground">{cohort.date ? formatDay(cohort.date) : cohort.label}</td>
                <td className="py-1 pr-3 text-right tabular-nums">{formatNumber(size)}</td>
                {Array.from({ length: columns }, (_, index) => {
                  const value = cohort.values?.[index];
                  if (!value) return <td key={index} />;
                  if (size === 0) return <td key={index} className="rounded bg-muted/40 py-1.5 text-center text-muted-foreground">–</td>;
                  const share = size > 0 ? Number(value.count ?? 0) / size : 0;
                  return (
                    <td
                      key={index}
                      className="rounded py-1.5 text-center tabular-nums"
                      style={{ background: "color-mix(in srgb, var(--primary) " + Math.round(8 + share * 72) + "%, transparent)", color: share > 0.55 ? "white" : undefined }}
                    >
                      {Math.round(share * 100)}%
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function BlockDescription({ text }: { text?: string }) {
  if (!text) return null;
  return <p className="text-xs text-muted-foreground">{text}</p>;
}

export function formatValue(value: number, format = "number"): string {
  if (!Number.isFinite(value)) return "–";
  if (format === "percent") return (Math.abs(value) >= 10 ? value.toFixed(0) : value.toFixed(1)) + "%";
  if (format === "currency") return "$" + formatNumber(value);
  if (format === "duration") {
    const seconds = Math.round(value);
    if (seconds < 60) return seconds + "s";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + "m " + (seconds % 60) + "s";
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
  }
  return formatNumber(value);
}
`;
