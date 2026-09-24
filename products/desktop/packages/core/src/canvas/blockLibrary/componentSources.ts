const METRIC = `import { Card, CardContent } from "@posthog/quill";
import { Area, AreaChart, ResponsiveContainer } from "recharts";
import {
  sqlNode,
  type BlockProps,
  BlockDescription,
  BlockState,
  CHART_COLORS,
  ChangeBadge,
  QueryButton,
  blockRoot,
  eventName,
  eventsNode,
  filterFields,
  formatNumber,
  formatValue,
  scopeLabel,
  useBlockQuery,
  useCanvasFilters,
} from "./runtime";

type MetricProps = BlockProps & {
  sql?: string;
  format?: "number" | "percent" | "currency" | "duration";
  title?: string;
  event?: string;
  math?: string;
  compare?: boolean;
  followFilters?: boolean;
};

export function Metric(props: MetricProps) {
  const { title, event = "$pageview", math = "total", compare = true, followFilters = true, sql, format = "number", description } = props;
  const filters = useCanvasFilters();
  const shared = { interval: filters.interval, ...filterFields(filters, followFilters) };
  const query = sql
    ? sqlNode(sql, filters, followFilters)
    : {
        kind: "TrendsQuery",
        series: [eventsNode(event, math)],
        trendsFilter: { display: "BoldNumber" },
        ...(compare ? { compareFilter: { compare: true } } : {}),
        ...shared,
      };
  const value = useBlockQuery(query);
  const spark = useBlockQuery(sql ? null : { kind: "TrendsQuery", series: [eventsNode(event, math)], ...shared });
  const rows = value.data?.results ?? [];
  const current = sql ? null : (rows.find((row) => row.compare_label !== "previous") ?? rows[0]);
  const previous = sql ? null : rows.find((row) => row.compare_label === "previous");
  const total = sql ? Number(rows[0]?.[0] ?? Number.NaN) : Number(current?.aggregated_value ?? current?.count ?? Number.NaN);
  const before = sql ? Number(rows[0]?.[1] ?? Number.NaN) : Number(previous?.aggregated_value ?? previous?.count ?? Number.NaN);
  const change = compare && Number.isFinite(before) && before !== 0 ? ((total - before) / Math.abs(before)) * 100 : null;
  const points = (spark.data?.results?.[0]?.data ?? []).map((point: number, index: number) => ({ index, value: Number(point) }));
  return (
    <Card {...blockRoot("Metric", props)} className="shrink-0 group relative flex min-w-0 flex-col">
      <QueryButton className="absolute top-3 right-3 rounded-md bg-card" query={query} hogql={value?.data?.hogql} />
      <CardContent className="flex flex-1 flex-col gap-1">
        <span className="truncate text-sm font-medium text-muted-foreground" title={title || eventName(event)}>{title || eventName(event)}</span>
        <BlockDescription text={description} />
        <BlockState loading={value.loading} error={value.error} empty={!Number.isFinite(total)} height={76}>
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-3xl font-semibold tracking-tight tabular-nums">{formatValue(total, format)}</span>
            {change === null ? null : <ChangeBadge value={change} />}
          </div>
          <div className="text-xs text-muted-foreground">{scopeLabel(filters, followFilters)}</div>
          {points.length > 1 ? (
            <div className="mt-auto h-12 pt-2">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={points} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
                  <Area type="monotone" dataKey="value" stroke={CHART_COLORS[0]} fill={CHART_COLORS[0]} fillOpacity={0.12} strokeWidth={1.5} isAnimationActive={false} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : null}
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const TREND = `import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  BlockDescription,
  sqlNode,
  type BlockProps,
  BlockState,
  CHART_COLORS,
  QueryButton,
  blockRoot,
  breakdownLabel,
  eventName,
  eventsNode,
  filterFields,
  fillDateRows,
  formatDay,
  previousRowsByDay,
  previousSqlNode,
  formatNumber,
  propertyLabel,
  scopeLabel,
  useBlockQuery,
  useCanvasFilters,
} from "./runtime";

type TrendProps = BlockProps & {
  title?: string;
  events?: string[];
  math?: string;
  display?: "line" | "bar" | "area";
  breakdown?: string;
  followFilters?: boolean;
};

const CHARTS = { line: LineChart, bar: BarChart, area: AreaChart };

export function Trend(props: TrendProps) {
  const { title, events = ["$pageview"], math = "total", display = "line", breakdown, followFilters = true, sql } = props;
  const filters = useCanvasFilters();
  const query = sql
    ? sqlNode(sql, filters, followFilters)
    : {
        kind: "TrendsQuery",
        series: events.map((event) => eventsNode(event, math)),
        interval: filters.interval,
        ...(breakdown ? { breakdownFilter: { breakdown, breakdown_type: "event", breakdown_limit: 5 } } : {}),
        ...(filters.compare ? { compareFilter: { compare: true } } : {}),
        ...filterFields(filters, followFilters),
      };
  const result = useBlockQuery(query);
  const previous = useBlockQuery(sql && filters.compare ? previousSqlNode(sql, filters, followFilters) : null);
  const series = sql ? [] : (result.data?.results ?? []);
  const baseColumns = sql ? (result.data?.columns ?? []).slice(1) : [];
  const previousRows = previous.data?.results ?? [];
  const comparing = !!sql && filters.compare && previousRows.length > 0;
  const previousByDay = comparing ? previousRowsByDay(previousRows.map((row) => String(row[0])), previousRows, filters.dateFrom) : null;
  const sqlColumns = comparing ? [...baseColumns, ...baseColumns.map((name) => name + " (previous)")] : baseColumns;
  const filled = sql
    ? fillDateRows((result.data?.results ?? []).map((row) => String(row[0])), result.data?.results ?? [], filters.dateFrom)
    : null;
  const sqlRows = filled ? filled.rows : [];
  const days: string[] = filled ? filled.xs : (series[0]?.days ?? []);
  const names = sql
    ? sqlColumns
    : series.map((row, index) => {
        const base = breakdown ? breakdownLabel(row.breakdown_value) : eventName(row.action?.id ?? events[index % events.length] ?? row.label ?? "Series");
        return row.compare_label === "previous" ? base + " (previous)" : base;
      });
  const previousAt = (index: number) => (sql ? comparing && index >= baseColumns.length : series[index]?.compare_label === "previous");
  const sqlValue = (day: string, index: number, seriesIndex: number) => {
    if (seriesIndex < baseColumns.length) return Number(sqlRows[index]?.[seriesIndex + 1] ?? 0);
    return Number(previousByDay?.get(day.slice(0, 10))?.[seriesIndex - baseColumns.length + 1] ?? 0);
  };
  const rows = days.map((day, index) => {
    const row: Record<string, number | string> = { day };
    names.forEach((_, seriesIndex) => {
      row["s" + seriesIndex] = sql ? sqlValue(day, index, seriesIndex) : Number(series[seriesIndex]?.data?.[index] ?? 0);
    });
    return row;
  });
  const colorAt = (index: number) => {
    if (sql) return CHART_COLORS[(comparing ? index % Math.max(1, baseColumns.length) : index) % CHART_COLORS.length];
    return CHART_COLORS[(filters.compare ? index % Math.max(1, names.length / 2) : index) % CHART_COLORS.length];
  };
  const Chart = CHARTS[display] ?? LineChart;
  return (
    <Card {...blockRoot("Trend", props)} className="shrink-0 group min-w-0">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="truncate">{title || events.map(eventName).join(", ")}</CardTitle>
          <BlockDescription text={props.description} />
          <div className="text-xs text-muted-foreground">
            {scopeLabel(filters, followFilters)}
            {breakdown && !sql ? " · by " + propertyLabel(breakdown) : ""}
          </div>
          {names.length > 1 ? (
            <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
              {names.map((name, index) => (
                <span key={name + index} className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                  <span className={"size-2 shrink-0 rounded-full" + (previousAt(index) ? " opacity-50" : "")} style={{ background: colorAt(index) }} />
                  <span className="truncate">{name}</span>
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <QueryButton query={query} hogql={result?.data?.hogql} />
      </CardHeader>
      <CardContent>
        <BlockState loading={result.loading} error={result.error} empty={rows.length === 0} height={220}>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <Chart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
                <CartesianGrid stroke="currentColor" strokeOpacity={0.08} vertical={false} />
                <XAxis dataKey="day" tickFormatter={formatDay} tick={{ fontSize: 11 }} stroke="currentColor" strokeOpacity={0.4} minTickGap={24} />
                <YAxis tickFormatter={formatNumber} tick={{ fontSize: 11 }} stroke="currentColor" strokeOpacity={0.4} width={48} />
                <Tooltip labelFormatter={formatDay} formatter={(value: number) => formatNumber(value)} />
                {names.map((_, index) => {
                  const color = colorAt(index);
                  const key = "s" + index;
                  const dash = previousAt(index) ? "4 4" : undefined;
                  const faded = previousAt(index) ? 0.5 : 1;
                  if (display === "bar") return <Bar key={key} dataKey={key} name={names[index]} fill={color} fillOpacity={faded} stackId={breakdown ? "stack" : undefined} radius={[3, 3, 0, 0]} isAnimationActive={false} />;
                  if (display === "area") return <Area key={key} dataKey={key} name={names[index]} type="monotone" stroke={color} strokeOpacity={faded} strokeDasharray={dash} fill={color} fillOpacity={previousAt(index) ? 0 : 0.15} strokeWidth={2} isAnimationActive={false} />;
                  return <Line key={key} dataKey={key} name={names[index]} type="monotone" stroke={color} strokeOpacity={faded} strokeDasharray={dash} strokeWidth={2} dot={false} isAnimationActive={false} />;
                })}
              </Chart>
            </ResponsiveContainer>
          </div>
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const TOP_LIST = `import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import {
  BlockDescription,
  sqlNode,
  type BlockProps,
  BlockState,
  QueryButton,
  blockRoot,
  breakdownLabel,
  eventName,
  eventsNode,
  filterFields,
  formatNumber,
  formatPercent,
  scopeLabel,
  useBlockQuery,
  useCanvasFilters,
} from "./runtime";

type TopListProps = BlockProps & {
  title?: string;
  event?: string;
  math?: string;
  breakdown?: string;
  limit?: number;
  followFilters?: boolean;
};

const OTHER = "$$_posthog_breakdown_other_$$";

export function TopList(props: TopListProps) {
  const { title, event = "$pageview", math = "total", breakdown = "$pathname", limit = 8, followFilters = true, sql } = props;
  const filters = useCanvasFilters();
  const query = sql
    ? sqlNode(sql, filters, followFilters)
    : {
        kind: "TrendsQuery",
        series: [eventsNode(event, math)],
        interval: filters.interval,
        trendsFilter: { display: "ActionsTable" },
        breakdownFilter: { breakdown, breakdown_type: "event", breakdown_limit: limit },
        ...filterFields(filters, followFilters),
      };
  const result = useBlockQuery(query);
  const rows = (result.data?.results ?? [])
    .map((row) =>
      sql
        ? { label: breakdownLabel(row[0]), other: false, value: Number(row[1] ?? 0) }
        : {
            label: breakdownLabel(row.breakdown_value),
            other: row.breakdown_value === OTHER,
            value: Number(row.aggregated_value ?? row.count ?? 0),
          },
    )
    .sort((a, b) => Number(a.other) - Number(b.other) || b.value - a.value)
    .slice(0, limit);
  const max = Math.max(1, ...rows.filter((row) => !row.other).map((row) => row.value));
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  return (
    <Card {...blockRoot("TopList", props)} className="shrink-0 group min-w-0">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="truncate">{title || "Top " + breakdown}</CardTitle>
          <BlockDescription text={props.description} />
          <div className="text-xs text-muted-foreground">{eventName(event)} · {scopeLabel(filters, followFilters)}</div>
        </div>
        <QueryButton query={query} hogql={result?.data?.hogql} />
      </CardHeader>
      <CardContent>
        <BlockState loading={result.loading} error={result.error} empty={rows.length === 0} height={200}>
          <div className="flex flex-col gap-1">
            {rows.map((row) => (
              <div key={row.label} className="relative flex items-center gap-3 rounded px-2 py-1.5 text-sm">
                <div className="absolute inset-y-0 left-0 rounded bg-primary/10" style={{ width: (row.value / max) * 100 + "%" }} />
                <span className="relative min-w-0 flex-1 truncate" title={row.label}>{row.label}</span>
                <span className="relative tabular-nums">{formatNumber(row.value)}</span>
                <span className="relative w-12 text-right text-xs text-muted-foreground tabular-nums">
                  {total > 0 ? formatPercent((row.value / total) * 100) : ""}
                </span>
              </div>
            ))}
          </div>
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const FUNNEL = `import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import {
  BlockDescription,
  sqlNode,
  type BlockProps,
  BlockState,
  QueryButton,
  blockRoot,
  eventName,
  filterFields,
  formatNumber,
  formatPercent,
  scopeLabel,
  useBlockQuery,
  useCanvasFilters,
} from "./runtime";

type FunnelProps = BlockProps & {
  title?: string;
  steps?: string[];
  windowDays?: number;
  followFilters?: boolean;
};

function literal(value: string) {
  return "'" + value.replace(/\\\\/g, "\\\\\\\\").replace(/'/g, "\\\\'") + "'";
}

export function Funnel(props: FunnelProps) {
  const { title, steps: builderSteps = ["$pageview", "$autocapture"], windowDays = 14, followFilters = true, sql } = props;
  const filters = useCanvasFilters();
  const conditions = builderSteps.map((step) => "event = " + literal(step)).join(", ");
  const builderQuery = {
    kind: "HogQLQuery",
    query:
      "SELECT level, count() AS people FROM (SELECT person_id, windowFunnel(" +
      windowDays * 86400 +
      ")(toDateTime(timestamp), " +
      conditions +
      ") AS level FROM events WHERE {filters} AND event IN (" +
      Array.from(new Set(builderSteps)).map(literal).join(", ") +
      ") GROUP BY person_id) GROUP BY level ORDER BY level",
    filters: filterFields(filters, followFilters),
  };
  const query = sql ? sqlNode(sql, filters, followFilters) : builderQuery;
  const result = useBlockQuery(query);
  const sqlRows = sql ? (result.data?.results ?? []) : [];
  const steps = sql ? sqlRows.map((row) => String(row[0])) : builderSteps;
  const byLevel = new Map<number, number>();
  if (!sql) for (const row of result.data?.results ?? []) byLevel.set(Number(row[0]), Number(row[1]));
  const counts = sql
    ? sqlRows.map((row) => Number(row[1] ?? 0))
    : steps.map((_, index) => {
        let reached = 0;
        for (const [level, people] of byLevel) if (level >= index + 1) reached += people;
        return reached;
      });
  const first = counts[0] ?? 0;
  const last = counts[counts.length - 1] ?? 0;
  return (
    <Card {...blockRoot("Funnel", props)} className="shrink-0 group min-w-0">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="truncate">{title || "Conversion"}</CardTitle>
          <BlockDescription text={props.description} />
          <div className="text-xs text-muted-foreground">
            {first > 0 ? formatPercent((last / first) * 100) + " convert · " : ""}
            {sql ? "" : windowDays + "-day window · "}
            {scopeLabel(filters, followFilters)}
          </div>
        </div>
        <QueryButton query={query} hogql={result?.data?.hogql} />
      </CardHeader>
      <CardContent>
        <BlockState loading={result.loading} error={result.error} empty={first === 0} height={160}>
          <div className="flex flex-col gap-2.5">
            {steps.map((step, index) => {
              const share = first > 0 ? (counts[index] / first) * 100 : 0;
              return (
                <div key={step + index} className="flex flex-col gap-1">
                  <div className="flex items-center justify-between text-sm">
                    <span className="truncate">{index + 1}. {eventName(step)}</span>
                    <span className="tabular-nums text-muted-foreground">
                      {formatNumber(counts[index])} · {formatPercent(share)}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-muted">
                    <div className="h-full rounded-full bg-primary transition-[width] duration-500" style={{ width: share + "%" }} />
                  </div>
                </div>
              );
            })}
          </div>
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const SQL_TABLE = `import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import {
  BlockDescription,
  type BlockProps,
  BlockState,
  QueryButton,
  ResultTable,
  blockRoot,
  filterFields,
  useBlockQuery,
  useCanvasFilters,
} from "./runtime";

type SqlTableProps = BlockProps & {
  title?: string;
  query?: string;
};

export function SqlTable(props: SqlTableProps) {
  const { title, query: hogql = "SELECT event, count() AS total FROM events WHERE {filters} GROUP BY event ORDER BY total DESC LIMIT 10" } = props;
  const filters = useCanvasFilters();
  const query = { kind: "HogQLQuery", query: hogql, filters: filterFields(filters) };
  const result = useBlockQuery(query);
  const columns = result.data?.columns ?? [];
  const rows = result.data?.results ?? [];
  return (
    <Card {...blockRoot("SqlTable", props)} className="shrink-0 group min-w-0">
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <CardTitle className="truncate">{title || "Query results"}</CardTitle>
        <BlockDescription text={props.description} />
        <QueryButton query={query} hogql={result?.data?.hogql} />
      </CardHeader>
      <CardContent>
        <BlockState loading={result.loading} error={result.error} empty={rows.length === 0} height={160}>
          <ResultTable columns={columns} rows={rows} />
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const DATE_RANGE = `import { Button } from "@posthog/quill";
import { type BlockProps, DATE_RANGES, blockRoot, setCanvasFilters, useCanvasFilters } from "./runtime";

export function DateRange(props: BlockProps) {
  const filters = useCanvasFilters();
  return (
    <div {...blockRoot("DateRange", props)} className="shrink-0 inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5 shadow-xs">
      {DATE_RANGES.map((range) => (
        <Button
          key={range.value}
          size="sm"
          variant={filters.dateFrom === range.value ? "primary" : "default"}
          onClick={() => setCanvasFilters({ ...filters, dateFrom: range.value })}
        >
          {range.label}
        </Button>
      ))}
    </div>
  );
}
`;

const INTERVAL = `import { Button } from "@posthog/quill";
import { type BlockProps, type CanvasInterval, blockRoot, setCanvasFilters, useCanvasFilters } from "./runtime";

const OPTIONS: Array<{ value: CanvasInterval; label: string }> = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
];

export function Interval(props: BlockProps) {
  const filters = useCanvasFilters();
  return (
    <div {...blockRoot("Interval", props)} className="shrink-0 inline-flex items-center gap-0.5 rounded-lg border border-border bg-card p-0.5 shadow-xs">
      {OPTIONS.map((option) => (
        <Button
          key={option.value}
          size="sm"
          variant={filters.interval === option.value ? "primary" : "default"}
          onClick={() => setCanvasFilters({ ...filters, interval: option.value })}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}
`;

const PROPERTY_FILTER = `import { type BlockProps, blockRoot, setCanvasFilters, useBlockQuery, useCanvasFilters } from "./runtime";

type PropertyFilterProps = BlockProps & {
  property?: string;
  label?: string;
};

export function PropertyFilter(props: PropertyFilterProps) {
  const { property = "$browser", label } = props;
  const filters = useCanvasFilters();
  const safe = property.replace(/[^A-Za-z0-9_$.-]/g, "");
  const values = useBlockQuery({
    kind: "HogQLQuery",
    query:
      "SELECT toString(properties." + "\`" + safe + "\`" + ") AS value, count() AS total FROM events WHERE timestamp > now() - INTERVAL 30 DAY AND properties." + "\`" + safe + "\`" + " IS NOT NULL GROUP BY value ORDER BY total DESC LIMIT 50",
  });
  const active = filters.properties.find((entry) => entry.key === property);
  const others = filters.properties.filter((entry) => entry.key !== property);
  const choose = (value: string) =>
    setCanvasFilters({
      ...filters,
      properties: value ? [...others, { key: property, value, type: "event" }] : others,
    });
  return (
    <label {...blockRoot("PropertyFilter", props)} className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-border bg-card p-0.5 pl-2.5 text-sm shadow-xs">
      <span className="text-muted-foreground">{label || property}</span>
      <select
        className={"h-7 max-w-40 cursor-pointer truncate rounded-md bg-transparent px-1.5 text-sm font-medium outline-none hover:bg-muted " + (active ? "text-primary" : "text-foreground")}
        value={active?.value ?? ""}
        onChange={(event) => choose(event.target.value)}
      >
        <option value="">All</option>
        {(values.data?.results ?? []).map((row) => (
          <option key={String(row[0])} value={String(row[0])}>{String(row[0])}</option>
        ))}
      </select>
    </label>
  );
}
`;

const FILTERS = `import { useEffect, useMemo, useState } from "react";
import { Button, Input, Popover, PopoverContent, PopoverTrigger } from "@posthog/quill";
import { CaretLeftIcon, FunnelIcon, PlusIcon, XIcon } from "./icons";
import {
  type BlockProps,
  type CanvasPropertyFilter,
  FILTER_OPERATORS,
  type FilterOperator,
  blockRoot,
  filterLabel,
  propertyLabel,
  setCanvasFilters,
  useBlockQuery,
  useCanvasFilters,
} from "./runtime";

type FiltersProps = BlockProps & { label?: string };
type Scope = "event" | "person";

const KEY_SOURCES: Record<Scope, string> = {
  event: "SELECT arrayJoin(JSONExtractKeys(properties)) AS k FROM events WHERE timestamp > now() - INTERVAL 7 DAY LIMIT 100000",
  person: "SELECT arrayJoin(JSONExtractKeys(properties)) AS k FROM persons LIMIT 50000",
};

function keysQuery(scope: Scope, search: string): string {
  const needle = search.replace(/[^A-Za-z0-9_$ .-]/g, "").trim();
  const where = needle ? " WHERE k ILIKE '%" + needle + "%'" : "";
  return "SELECT k, count() AS c FROM (" + KEY_SOURCES[scope] + ")" + where + " GROUP BY k ORDER BY c DESC LIMIT 200";
}

function useDebounced(value: string, delay: number): string {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}

function column(scope: Scope, key: string): string {
  const safe = key.replace(/[^A-Za-z0-9_$.-]/g, "");
  return (scope === "person" ? "person.properties." : "properties.") + "\`" + safe + "\`";
}

function valuesQuery(scope: Scope, key: string): string {
  const field = column(scope, key);
  return (
    "SELECT toString(" + field + ") AS value, count() AS c FROM events WHERE timestamp > now() - INTERVAL 30 DAY AND " +
    field + " IS NOT NULL GROUP BY value ORDER BY c DESC LIMIT 50"
  );
}

const COMMON_KEYS = [
  "$browser",
  "$os",
  "$device_type",
  "$pathname",
  "$current_url",
  "$referring_domain",
  "$geoip_country_name",
  "$geoip_city_name",
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "email",
  "name",
];

const INTERNAL_KEY = /^(\\$feature\\/|\\$feature_flag|\\$active_feature_flags|\\$set|\\$set_once|\\$lib|\\$sent_at|\\$insert_id|\\$time$|\\$window_id|\\$session_id|\\$device_id|\\$groups|\\$group_|\\$plugins|\\$raw_user_agent|\\$ip$|\\$process_person|\\$is_identified|\\$configured_session|\\$sdk|\\$exception|\\$debug|\\$replay|\\$recording|\\$web_vitals_|\\$heatmap|\\$dead_clicks|\\$surveys|\\$autocapture_disabled|\\$console_log|.*_server_side$|token$|distinct_id$)/;

function isInternalKey(name: string): boolean {
  return INTERNAL_KEY.test(name);
}

function commonRank(name: string): number {
  const index = COMMON_KEYS.indexOf(name);
  return index === -1 ? COMMON_KEYS.length : index;
}

function matchRank(name: string, needle: string): number {
  if (!needle) return 0;
  const key = name.toLowerCase().replace(/^\\$/, "");
  const label = propertyLabel(name).toLowerCase();
  if (key === needle || label === needle) return 0;
  if (key.startsWith(needle) || label.startsWith(needle)) return 1;
  if (key.includes(needle) || label.includes(needle)) return 2;
  return 3;
}

function needsValue(operator: FilterOperator): boolean {
  return operator !== "is_set" && operator !== "is_not_set";
}

function PickList({ items, onPick, empty }: { items: Array<{ value: string; label: string; hint?: string }>; onPick: (value: string) => void; empty: string }) {
  if (items.length === 0) return <div className="px-2 py-6 text-center text-xs text-muted-foreground">{empty}</div>;
  return (
    <div className="flex max-h-60 flex-col overflow-y-auto py-1">
      {items.map((item) => (
        <button
          key={item.value}
          type="button"
          onClick={() => onPick(item.value)}
          className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted"
        >
          <span className="min-w-0 shrink truncate">{item.label}</span>
          {item.hint ? <span className="min-w-0 shrink-[3] truncate text-xs text-muted-foreground tabular-nums">{item.hint}</span> : null}
        </button>
      ))}
    </div>
  );
}

function FilterEditor({ initial, onApply }: { initial: CanvasPropertyFilter | null; onApply: (filter: CanvasPropertyFilter) => void }) {
  const [scope, setScope] = useState<Scope>(initial?.type ?? "event");
  const [key, setKey] = useState<string | null>(initial?.key ?? null);
  const [operator, setOperator] = useState<FilterOperator>(initial?.operator ?? "exact");
  const [search, setSearch] = useState("");
  const keySearch = useDebounced(search, 200);
  const keys = useBlockQuery(key ? null : { kind: "HogQLQuery", query: keysQuery(scope, keySearch) });
  const values = useBlockQuery(key && needsValue(operator) ? { kind: "HogQLQuery", query: valuesQuery(scope, key) } : null);
  const needle = search.trim().toLowerCase();
  const keyItems = useMemo(
    () =>
      (keys.data?.results ?? [])
        .map((row) => String(row[0]))
        .filter((name) => !isInternalKey(name))
        .map((name, order) => ({ name, order, rank: matchRank(name, needle), common: commonRank(name) }))
        .filter((item) => item.rank < 3)
        .sort((a, b) => a.rank - b.rank || a.common - b.common || a.order - b.order)
        .map((item) => item.name)
        .slice(0, 80)
        .map((name) => ({ value: name, label: propertyLabel(name), hint: name.startsWith("$") ? name : undefined })),
    [keys.data, needle],
  );
  const valueItems = useMemo(
    () =>
      (values.data?.results ?? [])
        .map((row) => ({ value: String(row[0]), hint: Number(row[1]).toLocaleString() }))
        .filter((row) => !needle || row.value.toLowerCase().includes(needle))
        .map((row) => ({ value: row.value, label: row.value, hint: row.hint })),
    [values.data, needle],
  );
  const apply = (value: string) => {
    if (!key) return;
    onApply({ key, type: scope, operator, value });
  };

  if (!key) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex gap-1 rounded-md bg-muted p-0.5">
          {(["event", "person"] as Scope[]).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setScope(option)}
              className={"flex-1 rounded px-2 py-1 text-xs font-medium transition-colors " + (scope === option ? "bg-background shadow-xs" : "text-muted-foreground")}
            >
              {option === "event" ? "Event properties" : "Person properties"}
            </button>
          ))}
        </div>
        <Input autoFocus placeholder="Search properties" value={search} onChange={(event) => setSearch(event.target.value)} className="h-8" />
        {keys.loading && keyItems.length === 0 && !search ? <div className="h-40 animate-pulse rounded-md bg-muted/60" /> : <PickList items={keyItems} onPick={(value) => { setKey(value); setSearch(""); }} empty={keys.loading || search !== keySearch ? "Searching…" : "No properties match"} />}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <button type="button" onClick={() => setKey(null)} className="flex items-center gap-1 self-start text-xs text-muted-foreground transition-colors hover:text-foreground">
        <CaretLeftIcon className="size-3.5" />
        {(scope === "person" ? "Person " : "") + propertyLabel(key)}
      </button>
      <div className="flex flex-wrap gap-1">
        {FILTER_OPERATORS.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => {
              setOperator(option.value);
              if (!needsValue(option.value)) onApply({ key, type: scope, operator: option.value, value: "" });
            }}
            className={"rounded-md border px-2 py-0.5 text-xs transition-colors " + (operator === option.value ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:text-foreground")}
          >
            {option.label}
          </button>
        ))}
      </div>
      <Input
        autoFocus
        placeholder="Search or type a value"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && search.trim()) apply(search.trim());
        }}
        className="h-8"
      />
      {values.loading ? <div className="h-32 animate-pulse rounded-md bg-muted/60" /> : <PickList items={valueItems} onPick={apply} empty={search.trim() ? "Press Enter to use this value" : "No values yet"} />}
    </div>
  );
}

function FilterChip({ filter, onChange, onRemove }: { filter: CanvasPropertyFilter; onChange: (filter: CanvasPropertyFilter) => void; onRemove: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex items-center rounded-lg border border-border bg-card shadow-xs">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger render={<button type="button" className="px-2.5 py-1 text-sm transition-colors hover:text-primary" />}>
          {filterLabel(filter)}
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-2">
          <FilterEditor initial={filter} onApply={(next) => { onChange(next); setOpen(false); }} />
        </PopoverContent>
      </Popover>
      <button type="button" aria-label="Remove filter" onClick={onRemove} className="border-l border-border px-1.5 py-1.5 text-muted-foreground transition-colors hover:text-foreground">
        <XIcon className="size-3.5" />
      </button>
    </div>
  );
}

export function Filters(props: FiltersProps) {
  const filters = useCanvasFilters();
  const [adding, setAdding] = useState(false);
  const replace = (index: number, next: CanvasPropertyFilter | null) => {
    const properties = filters.properties.flatMap((current, position) => (position === index ? (next ? [next] : []) : [current]));
    setCanvasFilters({ ...filters, properties });
  };
  return (
    <div {...blockRoot("Filters", props)} className="flex shrink-0 flex-wrap items-center gap-1.5">
      <span className="flex items-center gap-1.5 pr-1 text-sm text-muted-foreground">
        <FunnelIcon className="size-4" />
        {props.label || "Filters"}
      </span>
      {filters.properties.map((filter, index) => (
        <FilterChip
          key={filter.type + filter.key + index}
          filter={filter}
          onChange={(next) => replace(index, next)}
          onRemove={() => replace(index, null)}
        />
      ))}
      <Popover open={adding} onOpenChange={setAdding}>
        <PopoverTrigger render={<Button variant="outline" size="sm" />}>
          <PlusIcon className="size-3.5" />
          Add filter
        </PopoverTrigger>
        <PopoverContent align="start" className="w-72 p-2">
          <FilterEditor
            initial={null}
            onApply={(next) => {
              setCanvasFilters({ ...filters, properties: [...filters.properties, next] });
              setAdding(false);
            }}
          />
        </PopoverContent>
      </Popover>
    </div>
  );
}
`;

const GOAL = `import { Card, CardContent } from "@posthog/quill";
import { sqlNode, type BlockProps, BlockDescription, BlockState, QueryButton, blockRoot, eventName, eventsNode, filterFields, formatNumber, formatValue, scopeLabel, useBlockQuery, useCanvasFilters } from "./runtime";

type GoalProps = BlockProps & {
  format?: "number" | "percent" | "currency" | "duration";
  title?: string;
  event?: string;
  math?: string;
  target?: number;
  followFilters?: boolean;
};

export function Goal(props: GoalProps) {
  const { title, event = "$pageview", math = "total", target = 1000, followFilters = true, sql, format = "number", description } = props;
  const filters = useCanvasFilters();
  const query = sql
    ? sqlNode(sql, filters, followFilters)
    : {
        kind: "TrendsQuery",
        series: [eventsNode(event, math)],
        trendsFilter: { display: "BoldNumber" },
        interval: filters.interval,
        ...filterFields(filters, followFilters),
      };
  const result = useBlockQuery(query);
  const row = result.data?.results?.[0];
  const total = sql ? Number(row?.[0] ?? Number.NaN) : Number(row?.aggregated_value ?? row?.count ?? Number.NaN);
  const share = target > 0 && Number.isFinite(total) ? total / target : 0;
  const reached = share >= 1;
  return (
    <Card
      {...blockRoot("Goal", props, {
        params: {
          title: { type: "text", label: "Title" },
          event: { type: "event", label: "Event" },
          math: {
            type: "select",
            label: "Measure",
            options: [
              { value: "total", label: "Total count" },
              { value: "dau", label: "Unique users" },
              { value: "weekly_active", label: "Weekly active" },
              { value: "monthly_active", label: "Monthly active" },
            ],
          },
          target: { type: "number", label: "Target", min: 1 },
          format: {
            type: "select",
            label: "Format",
            options: [
              { value: "number", label: "Number" },
              { value: "percent", label: "Percent" },
              { value: "currency", label: "Currency" },
              { value: "duration", label: "Duration" },
            ],
          },
          followFilters: { type: "boolean", label: "Use canvas filters", default: true },
        },
      })}
      className="group relative flex min-w-0 shrink-0 flex-col"
    >
      <QueryButton className="absolute top-3 right-3 rounded-md bg-card" query={query} hogql={result?.data?.hogql} />
      <CardContent className="flex flex-1 flex-col gap-2">
        <span className="truncate text-sm font-medium text-muted-foreground">{title || eventName(event) + " goal"}</span>
        <BlockDescription text={description} />
        <BlockState loading={result.loading} error={result.error} empty={!Number.isFinite(total)} height={72}>
          <div className="flex items-baseline gap-1.5">
            <span className="text-3xl font-semibold tracking-tight tabular-nums">{formatValue(total, format)}</span>
            <span className="text-sm text-muted-foreground tabular-nums">of {formatValue(target, format)}</span>
          </div>
          <div className="mt-3 h-2 overflow-hidden rounded-full bg-muted">
            <div
              className={"h-full origin-left rounded-full transition-transform duration-500 " + (reached ? "bg-emerald-500" : "bg-primary")}
              style={{ transform: "scaleX(" + Math.min(1, share) + ")", transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)" }}
            />
          </div>
          <div className="mt-1.5 flex justify-between text-xs text-muted-foreground">
            <span>{reached ? "Goal reached" : Math.round(share * 100) + "% of goal"}</span>
            <span>{scopeLabel(filters, followFilters)}</span>
          </div>
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const RECENT_EVENTS = `import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import { BlockDescription, sqlNode, type BlockProps, BlockState, QueryButton, blockRoot, eventName, filterFields, useBlockQuery, useCanvasFilters } from "./runtime";

type RecentEventsProps = BlockProps & {
  title?: string;
  limit?: number;
  followFilters?: boolean;
};

const REFRESH_MS = 15000;

function detailLabel(value: unknown): string {
  const text = value === null || value === undefined ? "" : String(value);
  return text === "/" ? "Home" : text;
}

function ago(value: unknown): string {
  const time = new Date(String(value)).getTime();
  if (!Number.isFinite(time)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - time) / 1000));
  if (seconds < 60) return seconds + "s ago";
  if (seconds < 3600) return Math.round(seconds / 60) + "m ago";
  if (seconds < 86400) return Math.round(seconds / 3600) + "h ago";
  return Math.round(seconds / 86400) + "d ago";
}

export function RecentEvents(props: RecentEventsProps) {
  const { title = "Recent events", limit = 12, followFilters = true, sql } = props;
  const filters = useCanvasFilters();
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((value) => value + 1), REFRESH_MS);
    return () => clearInterval(timer);
  }, []);
  const query = sqlNode(
    sql ||
      "SELECT timestamp, event, coalesce(toString(properties.$pathname), toString(properties.$current_url), '') AS place FROM events WHERE {filters} ORDER BY timestamp DESC LIMIT " +
        Math.max(1, Math.min(50, limit)),
    filters,
    followFilters,
  );
  const result = useBlockQuery(query, tick);
  const rows = result.data?.results ?? [];
  return (
    <Card
      {...blockRoot("RecentEvents", props, {
        params: {
          title: { type: "text", label: "Title" },
          limit: { type: "number", label: "Rows", min: 1, max: 50 },
          followFilters: { type: "boolean", label: "Use canvas filters", default: true },
        },
      })}
      className="group min-w-0 shrink-0"
    >
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle className="flex items-center gap-2 truncate">
          <span className="relative flex size-2">
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-500/60 motion-reduce:hidden" />
            <span className="relative inline-flex size-2 rounded-full bg-emerald-500" />
          </span>
          {title}
        </CardTitle>
        <BlockDescription text={props.description} />
        <QueryButton query={query} hogql={result?.data?.hogql} />
      </CardHeader>
      <CardContent>
        <BlockState loading={result.loading} error={result.error} empty={rows.length === 0} height={200}>
          <div className="flex flex-col">
            {rows.map((row, index) => (
              <div key={String(row[0]) + index} className="flex items-center gap-3 border-b border-border py-1.5 text-sm last:border-b-0">
                <span className="w-16 shrink-0 text-xs text-muted-foreground tabular-nums">{ago(row[0])}</span>
                <span className="shrink-0 font-medium">{eventName(String(row[1]))}</span>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{detailLabel(row[2])}</span>
              </div>
            ))}
          </div>
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const CALLOUT = `import { CheckCircleIcon, InfoIcon, WarningCircleIcon } from "./icons";
import { type BlockProps, blockRoot } from "./runtime";

type CalloutProps = BlockProps & {
  tone?: "info" | "success" | "warning";
  title?: string;
  text?: string;
};

const TONES = {
  info: { icon: InfoIcon, className: "border-border bg-muted/40", iconClassName: "text-muted-foreground" },
  success: { icon: CheckCircleIcon, className: "border-emerald-500/25 bg-emerald-500/5", iconClassName: "text-emerald-600" },
  warning: { icon: WarningCircleIcon, className: "border-amber-500/30 bg-amber-500/5", iconClassName: "text-amber-600" },
};

export function Callout(props: CalloutProps) {
  const { tone = "info", title = "Worth knowing", text = "Add a short note for the people who read this canvas." } = props;
  const look = TONES[tone] ?? TONES.info;
  const Icon = look.icon;
  return (
    <div
      {...blockRoot("Callout", props, {
        params: {
          tone: {
            type: "select",
            label: "Tone",
            options: [
              { value: "info", label: "Note" },
              { value: "success", label: "Good" },
              { value: "warning", label: "Warning" },
            ],
          },
          title: { type: "text", label: "Title" },
          text: { type: "longtext", label: "Text" },
        },
      })}
      className={"flex shrink-0 gap-3 rounded-xl border px-4 py-3 " + look.className}
    >
      <Icon className={"mt-0.5 size-4 shrink-0 " + look.iconClassName} />
      <div className="flex min-w-0 flex-col gap-0.5">
        {title ? <div className="text-sm font-medium">{title}</div> : null}
        <div className="text-sm text-muted-foreground">{text}</div>
      </div>
    </div>
  );
}
`;

const INSIGHT = `import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  type BlockProps,
  BlockDescription,
  BlockState,
  CHART_COLORS,
  RetentionGrid,
  blockRoot,
  breakdownLabel,
  eventName,
  formatDay,
  formatNumber,
  rangeLabel,
  useBlockInsight,
  useCanvasFilters,
  ResultTable,
} from "./runtime";

type InsightProps = BlockProps & {
  shortId?: string;
  title?: string;
  followFilters?: boolean;
};

const LIST_DISPLAYS = new Set(["ActionsTable", "ActionsPie", "ActionsBarValue", "WorldMap"]);
const BAR_DISPLAYS = new Set(["ActionsBar", "ActionsStackedBar", "ActionsUnstackedBar"]);

function seriesName(row: any, index: number): string {
  if (row.breakdown_value !== undefined && row.breakdown_value !== null && row.breakdown_value !== "") return breakdownLabel(row.breakdown_value);
  return eventName(String(row.label ?? row.action?.name ?? "Series " + (index + 1)));
}

function TrendsBody({ rows, display }: { rows: any[]; display: string }) {
  if (display === "BoldNumber") {
    const total = Number(rows[0]?.aggregated_value ?? rows[0]?.count ?? Number.NaN);
    return <div className="py-4 text-4xl font-semibold tracking-tight tabular-nums">{formatNumber(total)}</div>;
  }
  if (LIST_DISPLAYS.has(display)) {
    const items = rows.map((row, index) => ({ label: seriesName(row, index), value: Number(row.aggregated_value ?? row.count ?? 0) }));
    const max = Math.max(1, ...items.map((item) => item.value));
    return (
      <div className="flex flex-col gap-1">
        {items.slice(0, 10).map((item, index) => (
          <div key={item.label + index} className="relative flex items-center justify-between gap-3 overflow-hidden rounded-md px-2 py-1.5 text-sm">
            <span className="absolute inset-y-0 left-0 bg-primary/10" style={{ width: (item.value / max) * 100 + "%" }} />
            <span className="relative min-w-0 truncate">{item.label}</span>
            <span className="relative tabular-nums">{formatNumber(item.value)}</span>
          </div>
        ))}
      </div>
    );
  }
  const days: string[] = rows[0]?.days ?? rows[0]?.labels ?? [];
  const data = days.map((day, index) => {
    const point: Record<string, number | string> = { day };
    rows.forEach((row, seriesIndex) => {
      point["s" + seriesIndex] = Number(row.data?.[index] ?? 0);
    });
    return point;
  });
  const Chart = BAR_DISPLAYS.has(display) ? BarChart : display === "ActionsAreaGraph" ? AreaChart : LineChart;
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke="currentColor" strokeOpacity={0.08} vertical={false} />
          <XAxis dataKey="day" tickFormatter={formatDay} tick={{ fontSize: 11 }} stroke="currentColor" strokeOpacity={0.4} minTickGap={24} />
          <YAxis tickFormatter={formatNumber} tick={{ fontSize: 11 }} stroke="currentColor" strokeOpacity={0.4} width={48} />
          <Tooltip labelFormatter={formatDay} formatter={(value: number) => formatNumber(value)} />
          {rows.map((row, index) => {
            const color = CHART_COLORS[index % CHART_COLORS.length];
            const key = "s" + index;
            if (Chart === BarChart) return <Bar key={key} dataKey={key} name={seriesName(row, index)} fill={color} radius={[3, 3, 0, 0]} isAnimationActive={false} />;
            if (Chart === AreaChart) return <Area key={key} dataKey={key} name={seriesName(row, index)} type="monotone" stroke={color} fill={color} fillOpacity={0.15} strokeWidth={2} isAnimationActive={false} />;
            return <Line key={key} dataKey={key} name={seriesName(row, index)} type="monotone" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />;
          })}
        </Chart>
      </ResponsiveContainer>
    </div>
  );
}

function FunnelBody({ rows }: { rows: any[] }) {
  const steps: any[] = Array.isArray(rows[0]) ? rows[0] : rows;
  const first = Number(steps[0]?.count ?? 0);
  return (
    <div className="flex flex-col gap-2.5">
      {steps.map((step, index) => {
        const count = Number(step.count ?? 0);
        const share = first > 0 ? (count / first) * 100 : 0;
        return (
          <div key={index} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-sm">
              <span className="truncate">{index + 1}. {eventName(String(step.custom_name || step.name || "Step"))}</span>
              <span className="tabular-nums text-muted-foreground">{formatNumber(count)} · {Math.round(share)}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-primary" style={{ width: share + "%" }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Insight(props: InsightProps) {
  const { shortId = "", title, followFilters = true } = props;
  const filters = useCanvasFilters();
  const result = useBlockInsight(shortId || null, followFilters ? filters.dateFrom : null);
  const meta = result.data?.insight;
  const rows = result.data?.results ?? [];
  const kind = meta?.kind ?? "";
  const name = title || meta?.name || "Saved insight";
  const body = () => {
    if (kind === "TrendsQuery" || kind === "StickinessQuery" || kind === "LifecycleQuery") return <TrendsBody rows={rows} display={meta?.display ?? ""} />;
    if (kind === "FunnelsQuery") return <FunnelBody rows={rows} />;
    if (kind === "RetentionQuery") return <RetentionGrid cohorts={rows} period="period" />;
    if (kind === "HogQLQuery" || kind === "DataVisualizationNode" || kind === "DataTableNode") return <ResultTable columns={result.data?.columns ?? []} rows={rows} />;
    return <div className="py-8 text-center text-sm text-muted-foreground">This insight type opens in PostHog. Ask the agent to rebuild it here.</div>;
  };
  return (
    <Card
      {...blockRoot("Insight", props, {
        params: {
          shortId: { type: "insight", label: "Insight" },
          title: { type: "text", label: "Title", description: "Leave empty to use the insight's own name." },
          followFilters: { type: "boolean", label: "Use canvas date range", description: "Turn off to keep the dates saved in the insight.", default: true },
        },
      })}
      className="group min-w-0 shrink-0"
    >
      <CardHeader className="flex flex-col gap-0.5">
        <CardTitle className="truncate">{name}</CardTitle>
        <BlockDescription text={props.description} />
        <div className="text-xs text-muted-foreground">Saved insight · {followFilters ? rangeLabel(filters.dateFrom) : "Its own dates"}</div>
      </CardHeader>
      <CardContent>
        {shortId ? (
          <BlockState loading={result.loading} error={result.error} empty={rows.length === 0} height={200}>
            {body()}
          </BlockState>
        ) : (
          <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-border px-4 text-center text-sm text-muted-foreground">
            Pick a saved insight in the panel
          </div>
        )}
      </CardContent>
    </Card>
  );
}
`;

const RETENTION = `import { Card, CardContent, CardHeader, CardTitle } from "@posthog/quill";
import { type BlockProps, BlockDescription, BlockState, QueryButton, RetentionGrid, blockRoot, eventName, filterFields, scopeLabel, useBlockQuery, useCanvasFilters } from "./runtime";

type RetentionProps = BlockProps & {
  title?: string;
  startEvent?: string;
  returnEvent?: string;
  period?: "Day" | "Week" | "Month";
  intervals?: number;
  followFilters?: boolean;
};

export function Retention(props: RetentionProps) {
  const { title, startEvent = "$pageview", returnEvent = "$pageview", period = "Week", intervals = 8, followFilters = true, description } = props;
  const filters = useCanvasFilters();
  const query = {
    kind: "RetentionQuery",
    retentionFilter: {
      targetEntity: { id: startEvent, name: startEvent, type: "events" },
      returningEntity: { id: returnEvent, name: returnEvent, type: "events" },
      period,
      totalIntervals: Math.max(2, Math.min(16, intervals)),
      retentionType: "retention_first_time",
    },
    ...filterFields(filters, followFilters),
  };
  const result = useBlockQuery(query);
  const cohorts = result.data?.results ?? [];
  return (
    <Card
      {...blockRoot("Retention", props, {
        params: {
          title: { type: "text", label: "Title" },
          startEvent: { type: "event", label: "People who did" },
          returnEvent: { type: "event", label: "Came back to do" },
          period: { type: "select", label: "Period", options: ["Day", "Week", "Month"] },
          intervals: { type: "number", label: "Periods to show", min: 2, max: 16 },
          followFilters: { type: "boolean", label: "Use canvas filters", default: true },
        },
      })}
      className="group min-w-0 shrink-0"
    >
      <CardHeader className="flex flex-row items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <CardTitle className="truncate">{title || "Retention"}</CardTitle>
          <BlockDescription text={props.description} />
          <div className="text-xs text-muted-foreground">
            {eventName(startEvent)} then {eventName(returnEvent)} · {scopeLabel(filters, followFilters)}
          </div>
        </div>
        <QueryButton query={query} hogql={result?.data?.hogql} />
      </CardHeader>
      <CardContent>
        <BlockState loading={result.loading} error={result.error} empty={cohorts.length === 0} height={200}>
          <RetentionGrid cohorts={cohorts} period={period} />
        </BlockState>
      </CardContent>
    </Card>
  );
}
`;

const COMPARE = `import { type BlockProps, blockRoot, setCanvasFilters, useCanvasFilters } from "./runtime";

export function Compare(props: BlockProps) {
  const filters = useCanvasFilters();
  const on = !!filters.compare;
  return (
    <button
      {...blockRoot("Compare", props)}
      type="button"
      aria-pressed={on}
      onClick={() => setCanvasFilters({ ...filters, compare: !on })}
      className={"inline-flex h-[34px] shrink-0 items-center gap-2 rounded-lg border px-3 text-sm shadow-xs transition-colors duration-150 " + (on ? "border-primary/40 bg-primary/10 text-primary" : "border-border bg-card text-foreground")}
    >
      <span className={"relative block h-3.5 w-6 shrink-0 rounded-full transition-colors duration-150 " + (on ? "bg-primary" : "bg-muted-foreground/30")}>
        <span
          className="absolute top-0.5 left-0.5 block size-2.5 rounded-full bg-white shadow-xs transition-transform duration-150"
          style={{ transform: on ? "translateX(10px)" : "translateX(0)", transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)" }}
        />
      </span>
      Compare to previous
    </button>
  );
}
`;

const REFRESH = `import { useEffect, useRef, useState } from "react";
import { ArrowClockwiseIcon } from "./icons";
import { type BlockProps, blockRoot, refreshCanvasData, useLastUpdated } from "./runtime";

function sinceLabel(time: number | null, now: number): string {
  if (!time) return "Not loaded yet";
  const seconds = Math.max(0, Math.round((now - time) / 1000));
  if (seconds < 10) return "Updated just now";
  if (seconds < 60) return "Updated " + seconds + "s ago";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return "Updated " + minutes + "m ago";
  return "Updated " + Math.round(minutes / 60) + "h ago";
}

export function Refresh(props: BlockProps) {
  const updated = useLastUpdated();
  const [now, setNow] = useState(() => Date.now());
  const icon = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 10000);
    return () => clearInterval(timer);
  }, []);
  const refresh = () => {
    refreshCanvasData();
    setNow(Date.now());
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      icon.current?.animate([{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }], { duration: 500, easing: "cubic-bezier(0.23, 1, 0.32, 1)" });
    }
  };
  return (
    <button
      {...blockRoot("Refresh", props)}
      type="button"
      onClick={refresh}
      className="inline-flex h-[34px] shrink-0 items-center gap-2 rounded-lg border border-border bg-card px-3 text-sm text-muted-foreground shadow-xs transition-colors duration-150 hover:text-foreground"
    >
      <ArrowClockwiseIcon ref={icon} className="size-3.5" />
      {sinceLabel(updated, now)}
    </button>
  );
}
`;

export const BLOCK_COMPONENT_SOURCES: Record<string, string> = {
  Metric: METRIC,
  Trend: TREND,
  TopList: TOP_LIST,
  Funnel: FUNNEL,
  SqlTable: SQL_TABLE,
  DateRange: DATE_RANGE,
  Interval: INTERVAL,
  PropertyFilter: PROPERTY_FILTER,
  Filters: FILTERS,
  Goal: GOAL,
  RecentEvents: RECENT_EVENTS,
  Callout: CALLOUT,
  Insight: INSIGHT,
  Retention: RETENTION,
  Compare: COMPARE,
  Refresh: REFRESH,
};
