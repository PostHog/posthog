import type {
  ExperimentMetricResultPresentation,
  ExperimentVariantResultPresentation,
} from "@posthog/api-client/evidence-previews";
import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
  Badge,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
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

/** One-line verdict for a collapsed metric row: its strongest variant. */
function BestVariantLine({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement | null {
  const best = metric.bestVariant;
  if (!best) return null;
  return (
    <span
      className={`shrink-0 font-medium text-xs tabular-nums ${
        best.significance === "significant" && best.isImprovement === true
          ? "text-success"
          : best.significance === "significant" && best.isImprovement === false
            ? "text-destructive"
            : "text-muted-foreground"
      }`}
    >
      Best observed: {best.key} {best.uplift}
    </span>
  );
}

function MetricHeading({
  metric,
  compact,
}: {
  metric: ExperimentMetricResultPresentation;
  compact: boolean;
}): ReactElement {
  return (
    <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <span className="min-w-0">
        <Text
          render={<span />}
          size={compact ? "xs" : "sm"}
          weight="semibold"
          className="block truncate text-foreground"
        >
          {metric.name}
        </Text>
        {compact && (
          <Text
            render={<span />}
            size="xxs"
            variant="muted"
            className="block capitalize"
          >
            {metric.metricType} metric
          </Text>
        )}
      </span>
      <span className="flex shrink-0 items-center gap-2">
        <BestVariantLine metric={metric} />
        <MetricStateBadge metric={metric} />
      </span>
    </span>
  );
}

function MetricDetail({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement {
  if (metric.error) {
    return (
      <ExperimentResultNotice tone="destructive">
        {metric.error}
      </ExperimentResultNotice>
    );
  }
  if (metric.variants.length === 0) {
    return (
      <ExperimentResultNotice tone="neutral">
        No variant results are available for this metric yet.
      </ExperimentResultNotice>
    );
  }

  const control = metric.variants.find((variant) => variant.isControl);
  return (
    <div className="flex flex-col gap-2.5">
      {metric.controlOutcome && control && (
        <Text size="xxs" variant="muted" className="block tabular-nums">
          Control ({control.key}): {metric.controlOutcome}
        </Text>
      )}
      <div className="overflow-x-auto">
        <Table size="sm" className="min-w-[720px]">
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
              <TableRow
                key={variant.key}
                className={
                  variant.significance === "significant" &&
                  variant.isImprovement === true
                    ? "bg-success/5"
                    : variant.isControl
                      ? "text-muted-foreground"
                      : undefined
                }
              >
                <TableCell className="whitespace-nowrap font-medium">
                  {variant.key}
                  {variant.isControl ? " (control)" : ""}
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {variant.outcome}
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {variant.sampleContext}
                </TableCell>
                <TableCell
                  className={`whitespace-nowrap font-medium tabular-nums ${
                    variant.isImprovement === true
                      ? "text-success"
                      : variant.isImprovement === false
                        ? "text-destructive"
                        : ""
                  }`}
                >
                  {variant.uplift ?? "Baseline"}
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {variant.isControl
                    ? "Baseline"
                    : (variant.interval ?? "Not available")}
                </TableCell>
                <TableCell className="whitespace-nowrap tabular-nums">
                  {variant.isControl
                    ? "Baseline"
                    : variant.pValue
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
    </div>
  );
}

function CompactVariantRows({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement {
  if (metric.error) {
    return (
      <ExperimentResultNotice tone="destructive">
        {metric.error}
      </ExperimentResultNotice>
    );
  }
  if (metric.variants.length === 0) {
    return (
      <ExperimentResultNotice tone="neutral">
        No variant results yet.
      </ExperimentResultNotice>
    );
  }
  return (
    <div className="flex flex-col gap-2">
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
              className={`shrink-0 tabular-nums ${
                variant.isImprovement === true
                  ? "text-success"
                  : variant.isImprovement === false
                    ? "text-destructive"
                    : ""
              }`}
            >
              {variant.uplift ?? "Baseline"}
            </Text>
          </div>
          {!variant.isControl && (
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-muted-foreground tabular-nums">
              {variant.interval && <span>95% interval {variant.interval}</span>}
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
  );
}

export function ExperimentMetricResult({
  metric,
  display,
  defaultOpen = false,
}: {
  metric: ExperimentMetricResultPresentation;
  display: "compact" | "full";
  defaultOpen?: boolean;
}): ReactElement {
  if (display === "full") {
    return (
      <AccordionItem value={metric.id}>
        <AccordionTrigger
          data-attr="experiment-metric-toggle"
          className="[&>span:first-child]:min-w-0 [&>span:first-child]:flex-1"
        >
          <MetricHeading metric={metric} compact={false} />
        </AccordionTrigger>
        <AccordionContent>
          <MetricDetail metric={metric} />
        </AccordionContent>
      </AccordionItem>
    );
  }
  return (
    <Collapsible defaultOpen={defaultOpen}>
      <CollapsibleTrigger
        data-attr="experiment-metric-toggle"
        className="w-full rounded-md border border-border bg-card px-2.5 py-2 text-left"
      >
        <MetricHeading metric={metric} compact />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2">
          <CompactVariantRows metric={metric} />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
