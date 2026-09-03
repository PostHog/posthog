import type {
  ExperimentMetricResultPresentation,
  ExperimentVariantResultPresentation,
} from "@posthog/api-client/evidence-previews";
import {
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
  Badge,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Text,
} from "@posthog/quill";
import type { ReactElement } from "react";
import {
  ExperimentDeltaAxis,
  ExperimentDeltaBar,
} from "./ExperimentDeltaChart";
import { ExperimentResultNotice } from "./ExperimentResultNotice";

const SIGNIFICANCE_LABELS = {
  significant: "Significant",
  not_significant: "Not significant",
  insufficient_data: "Insufficient data",
} as const;

function directionClass(isImprovement: boolean | null): string {
  if (isImprovement === true) return "text-success-foreground";
  if (isImprovement === false) return "text-destructive-foreground";
  return "text-foreground";
}

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
        best.significance === "significant"
          ? directionClass(best.isImprovement)
          : "text-muted-foreground"
      }`}
    >
      Best observed: {best.key} {best.uplift}
    </span>
  );
}

function MetricHeading({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement {
  return (
    <span className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1">
      <Text
        render={<span />}
        size="sm"
        weight="semibold"
        className="min-w-0 truncate text-foreground"
      >
        {metric.name}
      </Text>
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

  const { axisRange } = metric;
  return (
    <div className="@container">
      <Table size="sm" fullWidth>
        <TableHeader>
          <TableRow>
            <TableHead>Variant</TableHead>
            <TableHead align="right">{metric.outcomeLabel}</TableHead>
            <TableHead align="right">Uplift</TableHead>
            <TableHead align="right">Significance</TableHead>
            {axisRange !== null && (
              <TableHead
                expand
                valign="bottom"
                className="@3xl:table-cell hidden"
              >
                <ExperimentDeltaAxis axisRange={axisRange} />
              </TableHead>
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {metric.variants.map((variant) => (
            <TableRow key={variant.key}>
              <TableCell valign="middle">
                <span className="block truncate font-medium">
                  {variant.key}
                  {variant.isControl ? " (control)" : ""}
                </span>
                <Text
                  render={<span />}
                  size="xxs"
                  variant="muted"
                  className="block truncate tabular-nums"
                >
                  {variant.sampleContext}
                </Text>
              </TableCell>
              <TableCell
                align="right"
                valign="middle"
                className="whitespace-nowrap tabular-nums"
              >
                {variant.outcome}
              </TableCell>
              <TableCell align="right" valign="middle">
                {variant.isControl || !variant.uplift ? (
                  <span className="text-muted-foreground">&mdash;</span>
                ) : (
                  <span
                    className={`whitespace-nowrap font-medium tabular-nums ${directionClass(variant.isImprovement)}`}
                  >
                    {variant.uplift}
                  </span>
                )}
              </TableCell>
              <TableCell align="right" valign="middle">
                {variant.isControl ? (
                  <span className="text-muted-foreground">&mdash;</span>
                ) : (
                  <>
                    <SignificanceBadge variant={variant} />
                    {(variant.pValue || variant.chanceToWin) && (
                      <Text
                        render={<span />}
                        size="xxs"
                        variant="muted"
                        className="mt-0.5 block whitespace-nowrap tabular-nums"
                      >
                        {variant.pValue
                          ? `p-value ${variant.pValue}`
                          : `${variant.chanceToWin} chance to win`}
                      </Text>
                    )}
                  </>
                )}
              </TableCell>
              {axisRange !== null && (
                <TableCell
                  expand
                  valign="middle"
                  className="@3xl:table-cell hidden pr-0"
                >
                  <ExperimentDeltaBar variant={variant} axisRange={axisRange} />
                </TableCell>
              )}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CompactMetricRow({
  metric,
}: {
  metric: ExperimentMetricResultPresentation;
}): ReactElement {
  const best = metric.bestVariant;
  const detail = metric.error
    ? "Query failed"
    : best
      ? `${best.key} vs control`
      : "No comparison yet";
  const significance =
    metric.state === "insufficient_data"
      ? "Insufficient data"
      : best?.significance
        ? SIGNIFICANCE_LABELS[best.significance]
        : null;
  return (
    <div className="flex items-baseline justify-between gap-3 px-2.5 py-2">
      <span className="min-w-0">
        <Text
          render={<span />}
          size="xs"
          weight="medium"
          className="block truncate text-foreground"
        >
          {metric.name}
        </Text>
        <Text
          render={<span />}
          size="xxs"
          variant="muted"
          className="block truncate"
        >
          {detail}
        </Text>
      </span>
      <span className="shrink-0 text-right">
        <Text
          render={<span />}
          size="xs"
          weight="semibold"
          className={`block tabular-nums ${
            best && best.significance === "significant"
              ? directionClass(best.isImprovement)
              : "text-foreground"
          }`}
        >
          {best?.uplift ?? "—"}
        </Text>
        {significance && (
          <Text render={<span />} size="xxs" variant="muted" className="block">
            {significance}
          </Text>
        )}
      </span>
    </div>
  );
}

export function ExperimentMetricResult({
  metric,
  display,
}: {
  metric: ExperimentMetricResultPresentation;
  display: "compact" | "full";
}): ReactElement {
  if (display === "compact") {
    return <CompactMetricRow metric={metric} />;
  }
  return (
    <AccordionItem value={metric.id}>
      <AccordionTrigger
        data-attr="experiment-metric-toggle"
        className="[&>span:first-child]:min-w-0 [&>span:first-child]:flex-1"
      >
        <MetricHeading metric={metric} />
      </AccordionTrigger>
      <AccordionContent>
        <MetricDetail metric={metric} />
      </AccordionContent>
    </AccordionItem>
  );
}
