import type { EvidencePreview } from "@posthog/api-client/evidence-previews";
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

export function PostHogObjectDetails({
  preview,
}: {
  preview: EvidencePreview;
}) {
  const sections = preview.sections ?? [];
  const showActivity = preview.spark && preview.spark.points.length > 1;
  const chart = preview.chart;

  if (!showActivity && !chart && sections.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {showActivity && preview.spark && (
        <Card size="sm">
          <CardContent className="p-4">
            <Text
              size="xs"
              weight="medium"
              variant="muted"
              className="uppercase tracking-wide"
            >
              Activity
            </Text>
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
          <CardContent className="p-4">
            <Text
              size="xs"
              weight="medium"
              variant="muted"
              className="uppercase tracking-wide"
            >
              {chart.title}
            </Text>
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
          <CardContent className="p-4">
            <Text
              size="xs"
              weight="medium"
              variant="muted"
              className="uppercase tracking-wide"
            >
              {section.title}
            </Text>
            <dl className="mt-3 grid gap-x-8 gap-y-4 sm:grid-cols-2">
              {section.fields.map((field) => (
                <div key={field.label} className="min-w-0">
                  <dt className="text-muted-foreground text-xs">
                    {field.label}
                  </dt>
                  <dd className="mt-1 break-words text-sm tabular-nums leading-relaxed">
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
