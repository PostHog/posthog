import {
  compactCount,
  type EvidencePreview,
} from "@posthog/api-client/evidence-previews";
import { Card, CardContent, Text } from "@posthog/quill";
import {
  TimeSeriesBarChart,
  TimeSeriesLineChart,
  useChartTheme,
} from "@posthog/quill-charts";
import { EvidenceSparkline } from "@posthog/ui/features/editor/components/EvidenceRefChip";

/**
 * A daily series as a real chart with hover values. The hover chip keeps the
 * passive sparkline; a full page has room for axes, a legend, and a tooltip.
 */
function DailySeriesChart({
  labels,
  series,
  render,
}: {
  labels: string[];
  series: Array<{ label: string; data: number[] }>;
  render: "line" | "bar";
}) {
  const theme = useChartTheme();
  const keyed = series.map((entry, index) => ({
    key: `series-${index}`,
    label: entry.label,
    data: entry.data,
  }));
  const config = {
    xAxis: { interval: "day" as const, timezone: "UTC" },
    legend: series.length > 1 ? { show: true } : undefined,
  };
  return (
    <div className="mt-2 flex h-40 w-full flex-col">
      {render === "bar" ? (
        <TimeSeriesBarChart
          series={keyed}
          labels={labels}
          theme={theme}
          config={config}
        />
      ) : (
        <TimeSeriesLineChart
          series={keyed}
          labels={labels}
          theme={theme}
          config={config}
        />
      )}
    </div>
  );
}

function CardTitle({ children }: { children: string }) {
  return (
    <Text
      variant="muted"
      className="block text-[11px] uppercase tracking-wider"
    >
      {children}
    </Text>
  );
}

/**
 * Latest point of a single series with its step change, so the chart answers
 * "where is it now?" without hovering. Mirrors the inbox report cards; the
 * delta stays uncolored because a rise here isn't necessarily good.
 */
function SeriesHeadline({ points }: { points: number[] }) {
  const last = points[points.length - 1];
  const previous = points.length > 1 ? points[points.length - 2] : null;
  if (typeof last !== "number" || !Number.isFinite(last)) return null;
  let delta: { label: string; up: boolean } | null = null;
  if (
    typeof previous === "number" &&
    Number.isFinite(previous) &&
    previous !== 0
  ) {
    const pct = ((last - previous) / Math.abs(previous)) * 100;
    if (Math.abs(pct) >= 0.5) {
      delta = {
        label: `${Math.abs(pct) >= 10 ? Math.round(Math.abs(pct)) : Math.abs(pct).toFixed(1)}%`,
        up: pct >= 0,
      };
    }
  }
  return (
    <span className="flex shrink-0 items-baseline gap-1.5">
      <span className="font-semibold text-[15px] text-foreground tabular-nums leading-none">
        {compactCount(last)}
      </span>
      {delta && (
        <span className="font-medium text-[11px] text-muted-foreground tabular-nums">
          {delta.up ? "▲" : "▼"}
          {delta.label}
        </span>
      )}
    </span>
  );
}

type Section = NonNullable<EvidencePreview["sections"]>[number];

/**
 * Merge sections that share a heading into one card, so a field never lands
 * under a title that belongs to a different section. A uniquely-titled section
 * keeps its own card even when it holds a single field: a correct one-field
 * card beats folding a fact under a heading that contradicts it.
 */
export function foldSections(sections: Section[]): Section[] {
  const byTitle = new Map<string, Section>();
  const order: string[] = [];
  for (const section of sections) {
    const existing = byTitle.get(section.title);
    if (existing) {
      existing.fields = [...existing.fields, ...section.fields];
    } else {
      byTitle.set(section.title, { ...section, fields: [...section.fields] });
      order.push(section.title);
    }
  }
  return order.map((title) => byTitle.get(title) as Section);
}

export function PostHogObjectDetails({
  preview,
}: {
  preview: EvidencePreview;
}) {
  const sections = foldSections(preview.sections ?? []);
  const showActivity = preview.spark && preview.spark.points.length > 1;
  const chart = preview.chart;

  if (!showActivity && !chart && sections.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {showActivity && preview.spark && (
        <Card size="sm">
          <CardContent>
            <div className="flex items-center justify-between gap-2">
              <CardTitle>Activity</CardTitle>
              <SeriesHeadline points={preview.spark.points} />
            </div>
            {preview.spark.labels &&
            preview.spark.labels.length === preview.spark.points.length ? (
              <DailySeriesChart
                labels={preview.spark.labels}
                series={[{ label: "Activity", data: preview.spark.points }]}
                render={preview.spark.render}
              />
            ) : (
              <EvidenceSparkline
                points={preview.spark.points}
                render={preview.spark.render}
              />
            )}
          </CardContent>
        </Card>
      )}
      {chart && (
        <Card size="sm">
          <CardContent>
            <CardTitle>{chart.title}</CardTitle>
            <DailySeriesChart
              labels={chart.labels}
              series={chart.series}
              render={chart.render}
            />
          </CardContent>
        </Card>
      )}
      {sections.map((section) => (
        <Card key={section.title} size="sm">
          <CardContent>
            <CardTitle>{section.title}</CardTitle>
            <dl className="mt-2.5 flex flex-col">
              {section.fields.map((field, index) => (
                <div
                  key={`${field.label}:${index}`}
                  className="flex items-baseline gap-4 py-[5px]"
                >
                  <dt className="w-40 shrink-0 text-muted-foreground text-xs">
                    {field.label}
                  </dt>
                  <dd className="min-w-0 break-words font-medium text-[13px] text-foreground tabular-nums leading-snug">
                    {field.value}
                  </dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
