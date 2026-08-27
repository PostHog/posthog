import type {
  ExperimentMetricResultPresentation,
  ExperimentVariantResultPresentation,
} from "@posthog/api-client/evidence-previews";
import {
  Badge,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Text,
} from "@posthog/quill";
import type { ReactElement } from "react";
import { ExperimentResultNotice } from "./ExperimentResultNotice";

const SIGNIFICANCE_LABELS = {
  significant: "Significant",
  not_significant: "Not significant",
  insufficient_data: "Insufficient data",
} as const;

function MetricStateBadge({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement | null {
  if (metric.state === "error") {
    return <Badge variant="destructive">Query failed</Badge>;
  }
  if (metric.state === "insufficient_data") {
    return <Badge variant="warning">Insufficient data</Badge>;
  }
  return null;
}

function SignificanceBadge({
  variant,
}: {
  variant: ExperimentVariantResultPresentation;
}): ReactElement {
  if (!variant.significance) {
    return <span className="text-muted-foreground">Not available</span>;
  }
  return (
    <Badge
      variant={
        variant.significance === "significant"
          ? "success"
          : variant.significance === "insufficient_data"
            ? "warning"
            : "default"
      }
    >
      {SIGNIFICANCE_LABELS[variant.significance]}
    </Badge>
  );
}

function CompactMetric({
  metric,
  showStatistics,
}: {
  metric: ExperimentMetricResultPresentation;
  showStatistics: boolean;
}): ReactElement {
  return (
    <div className="rounded-md border border-border bg-card p-2.5">
      <div className="flex min-w-0 items-center justify-between gap-2">
        <div className="min-w-0">
          <Text
            size="xs"
            weight="semibold"
            className="block truncate text-foreground"
          >
            {metric.name}
          </Text>
          <Text size="xxs" variant="muted" className="capitalize">
            {metric.metricType} metric
          </Text>
        </div>
        <MetricStateBadge metric={metric} />
      </div>
      {metric.error ? (
        <Text size="xs" variant="muted" className="mt-2 block">
          {metric.error}
        </Text>
      ) : metric.variants.length === 0 ? (
        <Text size="xs" variant="muted" className="mt-2 block">
          No variant results yet.
        </Text>
      ) : (
        <div className="mt-2 flex flex-col gap-2">
          {metric.variants.map((variant) => (
            <div key={variant.key} className="min-w-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Text size="xs" weight="medium" className="block truncate">
                    {variant.key}
                    {variant.isControl ? " (control)" : ""}
                  </Text>
                  <Text
                    size="xxs"
                    variant="muted"
                    className="block break-words tabular-nums"
                  >
                    {variant.outcome} · {variant.sampleContext}
                  </Text>
                </div>
                <Text
                  size="xs"
                  weight="semibold"
                  className="shrink-0 tabular-nums"
                >
                  {variant.uplift ?? "Baseline"}
                </Text>
              </div>
              {showStatistics && !variant.isControl && (
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-muted-foreground tabular-nums">
                  {variant.interval && (
                    <span>95% interval {variant.interval}</span>
                  )}
                  {variant.pValue && <span>p-value {variant.pValue}</span>}
                  {variant.chanceToWin && (
                    <span>{variant.chanceToWin} chance to win</span>
                  )}
                  <SignificanceBadge variant={variant} />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FullMetric({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement {
  return (
    <Card size="sm" flush>
      <div className="flex flex-wrap items-center justify-between gap-2 border-border border-b px-3 py-2.5">
        <div>
          <Text size="sm" weight="semibold" className="block">
            {metric.name}
          </Text>
          <Text size="xs" variant="muted" className="capitalize">
            {metric.metricType} metric
          </Text>
        </div>
        <MetricStateBadge metric={metric} />
      </div>
      <CardContent>
        {metric.error ? (
          <div className="p-3">
            <ExperimentResultNotice tone="destructive">
              {metric.error}
            </ExperimentResultNotice>
          </div>
        ) : metric.variants.length === 0 ? (
          <div className="p-3">
            <ExperimentResultNotice tone="neutral">
              No variant results are available for this metric yet.
            </ExperimentResultNotice>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <Table size="sm" className="min-w-[760px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Variant</TableHead>
                  <TableHead>{metric.outcomeLabel}</TableHead>
                  <TableHead>Sample and exposure</TableHead>
                  <TableHead>Uplift</TableHead>
                  <TableHead>95% interval</TableHead>
                  <TableHead>Statistical measure</TableHead>
                  <TableHead>Significance</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {metric.variants.map((variant) => (
                  <TableRow key={variant.key}>
                    <TableCell className="font-medium">
                      {variant.key}
                      {variant.isControl ? " (control)" : ""}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {variant.outcome}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {variant.sampleContext}
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-medium tabular-nums">
                      {variant.uplift ?? "Baseline"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {variant.interval ?? "Not available"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums">
                      {variant.pValue
                        ? `p-value ${variant.pValue}`
                        : variant.chanceToWin
                          ? `${variant.chanceToWin} chance to win`
                          : "Not available"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      {variant.isControl ? (
                        <span className="text-muted-foreground">Baseline</span>
                      ) : (
                        <SignificanceBadge variant={variant} />
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function ExperimentMetricResult({
  metric,
  display,
  showStatistics,
}: {
  metric: ExperimentMetricResultPresentation;
  display: "compact" | "full";
  showStatistics: boolean;
}): ReactElement {
  return display === "compact" ? (
    <CompactMetric metric={metric} showStatistics={showStatistics} />
  ) : (
    <FullMetric metric={metric} />
  );
}
