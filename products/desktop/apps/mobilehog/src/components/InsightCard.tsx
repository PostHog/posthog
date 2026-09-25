import { requestErrorStatus } from "@posthog/api-client/fetcher";
import {
  getObjectKind,
  type ObjectTagRef,
  objectWebPath,
} from "@posthog/core/inbox/objectTags";
import {
  planReportChart,
  type ReportChartData,
  shapeReportChartData,
} from "@posthog/core/inbox/reportCharts";
import { isSafeExternalUrl } from "@posthog/shared";
import type { SignalReportChart } from "@posthog/shared/domain-types";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  ActivityIndicator,
  Linking,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { getBaseUrl, getProjectId } from "@/lib/api";
import { getClient } from "@/lib/client";
import { colors, fonts } from "@/lib/theme";

const palette = ["#F54E00", "#1D4AFF", "#39823A", "#9564D9", "#B56C08"];

export function InsightCard({
  reference,
  definition,
}: {
  reference?: ObjectTagRef;
  definition?: SignalReportChart;
}) {
  const { kind, id, label } = reference ?? {
    kind: "report-chart",
    id: definition?.chart_id ?? "",
    label: definition?.title ?? "Chart",
  };
  const isChart = kind === "insight" || kind === "hogql" || !!definition;
  const chart = useQuery({
    queryKey: ["message-chart", kind, id, definition?.query],
    enabled: isChart,
    staleTime: 5 * 60_000,
    retry: 1,
    queryFn: async () => {
      const client = getClient();
      if (kind === "hogql") {
        const plan = {
          kind: "run" as const,
          source: { kind: "HogQLQuery", query: id },
          render: "auto" as const,
        };
        return {
          name: label,
          data: shapeReportChartData(await client.runQuery(plan.source), plan),
        };
      }
      let query = definition?.query;
      let name = label;
      if (!definition) {
        const insight = await client.getInsightDefinition(id);
        if (!insight) throw new Error("Insight not found");
        query = insight.query;
        name = insight.name || label;
      }
      let plan = planReportChart(query);
      if (plan.kind === "saved-insight") {
        const insight = await client.getInsightDefinition(plan.shortId);
        if (!insight) throw new Error("Insight not found");
        plan = planReportChart(insight.query);
      }
      return {
        name,
        data:
          plan.kind === "run"
            ? shapeReportChartData(await client.runQuery(plan.source), plan)
            : null,
      };
    },
  });
  const saved = definition ? planReportChart(definition.query) : null;
  const path =
    saved?.kind === "saved-insight"
      ? objectWebPath("insight", saved.shortId)
      : objectWebPath(kind, id);
  const url = path ? `${getBaseUrl()}/project/${getProjectId()}${path}` : null;
  return (
    <View style={styles.card}>
      <Text style={styles.title}>
        {chart.data?.name ||
          (label === id ? getObjectKind(kind).kindLabel : label)}
      </Text>
      {isChart && chart.isPending ? (
        <ActivityIndicator
          accessibilityLabel="Loading chart"
          color={colors.accent}
        />
      ) : null}
      {chart.isError ? (
        <Pressable
          accessibilityRole="button"
          disabled={chart.isFetching}
          onPress={() => void chart.refetch()}
        >
          <Text style={styles.link}>
            {requestErrorStatus(chart.error) === 403
              ? "Chart access was denied. Sign in again to grant insight access, or check your project permissions."
              : "Could not load chart. Tap to retry."}
          </Text>
        </Pressable>
      ) : null}
      {chart.data?.data ? (
        <Chart data={chart.data.data} />
      ) : chart.isSuccess && isChart ? (
        <Text style={styles.note}>
          {url
            ? "Open this insight in PostHog to see its visualization."
            : "This chart type is not available on mobile."}
        </Text>
      ) : null}
      {definition?.caption ? (
        <Text style={styles.note}>{definition.caption}</Text>
      ) : null}
      {url && isSafeExternalUrl(url) ? (
        <Pressable
          accessibilityRole="link"
          onPress={() => void Linking.openURL(url).catch(() => {})}
        >
          <Text style={styles.link}>Open in PostHog ↗</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

function cell(value: unknown): string {
  return typeof value === "object" && value !== null
    ? JSON.stringify(value)
    : String(value ?? "—");
}

function Chart({ data }: { data: ReportChartData }) {
  const [showData, setShowData] = useState(false);
  if (data.type === "empty")
    return <Text style={styles.note}>No data for this period.</Text>;
  if (data.type === "number")
    return <Text style={styles.number}>{data.value.toLocaleString()}</Text>;
  if (data.type === "table")
    return <DataTable columns={data.columns} rows={data.rows} />;
  return (
    <View style={{ gap: 10 }}>
      <SeriesChart data={data} />
      {data.series.map((series, index) => (
        <Text
          key={series.key}
          style={[styles.note, { color: palette[index % palette.length] }]}
        >
          {series.label}
        </Text>
      ))}
      <Pressable
        accessibilityRole="button"
        onPress={() => setShowData(!showData)}
      >
        <Text style={styles.link}>
          {showData ? "Hide values" : "Show values"}
        </Text>
      </Pressable>
      {showData ? (
        <DataTable
          columns={["Period", ...data.series.map((series) => series.label)]}
          rows={data.labels.map((label, index) => [
            label,
            ...data.series.map((series) => series.data[index]),
          ])}
        />
      ) : null}
    </View>
  );
}

function DataTable({
  columns,
  rows,
}: {
  columns: string[];
  rows: unknown[][];
}) {
  return (
    <ScrollView horizontal>
      <View>
        <View style={styles.tableRow}>
          {columns.map((column, index) => (
            <Text
              key={`${index}-${column}`}
              style={[styles.cell, styles.title]}
            >
              {column}
            </Text>
          ))}
        </View>
        {rows.slice(0, 100).map((row, index) => (
          <View key={`${index}-${cell(row[0])}`} style={styles.tableRow}>
            {columns.map((column, i) => (
              <Text selectable key={`${i}-${column}`} style={styles.cell}>
                {cell(row[i])}
              </Text>
            ))}
          </View>
        ))}
        {rows.length > 100 ? (
          <Text style={styles.note}>
            Showing the first 100 rows. Open in PostHog for all results.
          </Text>
        ) : null}
      </View>
    </ScrollView>
  );
}

function SeriesChart({
  data,
}: {
  data: Extract<ReportChartData, { type: "series" }>;
}) {
  const [width, setWidth] = useState(280);
  const values = data.series
    .flatMap((series) => series.data)
    .filter(Number.isFinite);
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const range = max - min || 1;
  const height = 150;
  const y = (value: number) => height - ((value - min) / range) * height;
  const count = data.labels.length;
  const step = width / Math.max(count, 1);
  return (
    <View style={{ gap: 6 }}>
      <Text style={styles.note}>{max.toLocaleString()}</Text>
      <View
        onLayout={(event) => setWidth(event.nativeEvent.layout.width)}
        style={{ height, overflow: "hidden" }}
        accessibilityLabel={`${data.render} chart. Select Show values to read the data.`}
      >
        <View
          style={{
            position: "absolute",
            top: y(0),
            height: 1,
            width: "100%",
            backgroundColor: colors.line,
          }}
        />
        {data.series.flatMap((series, seriesIndex) =>
          series.data.map((value, index) => {
            if (!Number.isFinite(value)) return null;
            const color = palette[seriesIndex % palette.length];
            const x = step * (index + 0.5);
            if (data.render === "bar") {
              const barWidth = Math.max(1, (step * 0.8) / data.series.length);
              return (
                <View
                  key={`${series.key}-${index}`}
                  style={{
                    position: "absolute",
                    left: step * index + step * 0.1 + seriesIndex * barWidth,
                    top: Math.min(y(0), y(value)),
                    width: barWidth,
                    height: Math.max(1, Math.abs(y(value) - y(0))),
                    backgroundColor: color,
                  }}
                />
              );
            }
            const previous = series.data[index - 1];
            if (index === 0 || !Number.isFinite(previous))
              return (
                <View
                  key={`${series.key}-${index}`}
                  style={{
                    position: "absolute",
                    left: x - 2,
                    top: y(value) - 2,
                    width: 4,
                    height: 4,
                    borderRadius: 2,
                    backgroundColor: color,
                  }}
                />
              );
            const dy = y(value) - y(previous);
            const length = Math.hypot(step, dy);
            return (
              <View
                key={`${series.key}-${index}`}
                style={{
                  position: "absolute",
                  left: x - step / 2 - length / 2,
                  top: (y(value) + y(previous)) / 2,
                  width: length,
                  height: 2,
                  backgroundColor: color,
                  transform: [{ rotate: `${Math.atan2(dy, step)}rad` }],
                }}
              />
            );
          }),
        )}
      </View>
      <Text style={styles.note}>{min.toLocaleString()}</Text>
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          gap: 8,
        }}
      >
        <Text style={styles.axis} numberOfLines={1}>
          {data.labels[0]}
        </Text>
        <Text style={styles.axis} numberOfLines={1}>
          {data.labels[count - 1]}
        </Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    padding: 14,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    borderRadius: 14,
    gap: 12,
  },
  title: { fontFamily: fonts.sansSemi, fontSize: 15, color: colors.ink },
  number: { fontFamily: fonts.sansBold, fontSize: 32, color: colors.ink },
  note: { fontFamily: fonts.sans, fontSize: 12, color: colors.inkSoft },
  link: {
    fontFamily: fonts.sansMedium,
    fontSize: 14,
    color: colors.accent,
    paddingVertical: 5,
  },
  axis: {
    fontFamily: fonts.sans,
    fontSize: 11,
    color: colors.inkMute,
    flexShrink: 1,
  },
  tableRow: {
    flexDirection: "row",
    borderBottomWidth: 1,
    borderColor: colors.line,
  },
  cell: {
    width: 120,
    padding: 8,
    fontFamily: fonts.sans,
    fontSize: 12,
    color: colors.ink,
  },
});
