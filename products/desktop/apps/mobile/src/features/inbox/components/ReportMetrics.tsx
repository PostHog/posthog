import { Text } from "@components/text";
import {
  orderedReportMetrics,
  reportMetricSnapshot,
} from "@posthog/core/inbox/reportMetrics";
import type { SignalReportMetric } from "@posthog/shared/domain-types";
import { View } from "react-native";

function MetricTile({ metric }: { metric: SignalReportMetric }) {
  const snapshot = reportMetricSnapshot(metric, { compact: true });

  return (
    <View className="min-w-[45%] flex-1 rounded-lg border border-gray-5 px-3 py-2">
      <Text className="text-[12px] text-gray-9" numberOfLines={1}>
        {metric.title}
      </Text>
      <View className="flex-row items-baseline gap-1.5">
        <Text className="font-semibold text-[18px] text-gray-12">
          {snapshot ? snapshot.value : "Not measured"}
        </Text>
        {snapshot?.trend && (
          // Direction only: a rise in errors, latency or cost is not good news,
          // so the arrow stays uncoloured.
          <Text className="text-[12px] text-gray-9">
            {snapshot.trend.direction === "up" ? "▲" : "▼"}
            {snapshot.trend.label}
          </Text>
        )}
      </View>
      {metric.caption ? (
        <Text className="text-[11px] text-gray-9" numberOfLines={2}>
          {metric.caption}
        </Text>
      ) : null}
    </View>
  );
}

/**
 * What the report measured, from the snapshots the list and detail responses
 * already carry. Mobile does not run the live query, so a metric with no
 * snapshot reads as not measured rather than as zero.
 */
export function ReportMetrics({
  metrics,
}: {
  metrics: SignalReportMetric[] | undefined;
}) {
  const ordered = orderedReportMetrics(metrics);
  if (ordered.length === 0) return null;

  return (
    <View className="mb-4 flex-row flex-wrap gap-2">
      {ordered.map((metric) => (
        <MetricTile key={metric.metric_id} metric={metric} />
      ))}
    </View>
  );
}
