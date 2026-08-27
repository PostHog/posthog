import type { ExperimentResultsPresentation } from "@posthog/api-client/evidence-previews";
import { Button, Skeleton } from "@posthog/quill";
import { type ReactElement, useState } from "react";
import { ExperimentMetricResult } from "./ExperimentMetricResult";
import { ExperimentResultNotice } from "./ExperimentResultNotice";

export interface ExperimentResultsSummaryProps {
  display: "compact" | "full";
  loadState: "loading" | "error" | "missing" | "ready";
  results: ExperimentResultsPresentation | null | undefined;
}

export function ExperimentResultsSummary({
  display,
  loadState,
  results,
}: ExperimentResultsSummaryProps): ReactElement {
  const [expanded, setExpanded] = useState(false);

  if (loadState === "loading") {
    return (
      <div
        className="flex flex-col gap-2"
        data-testid="experiment-results-loading"
      >
        <Skeleton
          className={display === "compact" ? "h-20 w-full" : "h-36 w-full"}
        />
        {display === "full" && <Skeleton className="h-36 w-full" />}
      </div>
    );
  }
  if (loadState === "error") {
    return (
      <ExperimentResultNotice tone="destructive">
        Couldn't load experiment results. Try again, or open the experiment in
        PostHog.
      </ExperimentResultNotice>
    );
  }
  if (!results || loadState === "missing") {
    return (
      <ExperimentResultNotice tone="neutral">
        Experiment results are not available in the current project.
      </ExperimentResultNotice>
    );
  }
  if (results.state === "draft") {
    return (
      <ExperimentResultNotice tone="neutral">
        Results will appear after this experiment starts.
      </ExperimentResultNotice>
    );
  }

  const metrics = [...results.primaryMetrics, ...results.secondaryMetrics];
  const visibleMetrics =
    display === "compact" && !expanded ? metrics.slice(0, 1) : metrics;
  const hiddenMetricCount = metrics.length - visibleMetrics.length;

  return (
    <div className="flex flex-col gap-2" data-testid="experiment-results">
      {results.stale && (
        <ExperimentResultNotice tone="warning">
          Cached results may be out of date
          {results.lastRefresh
            ? `. Last refreshed ${new Date(results.lastRefresh).toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" })}.`
            : "."}
        </ExperimentResultNotice>
      )}
      {results.state === "error" && (
        <ExperimentResultNotice tone="destructive">
          Some metric results couldn't load. Open the experiment in PostHog to
          retry them.
        </ExperimentResultNotice>
      )}
      {results.state === "insufficient_data" && (
        <ExperimentResultNotice tone="warning">
          There isn't enough data to determine significance yet.
        </ExperimentResultNotice>
      )}
      {metrics.length === 0 ? (
        <ExperimentResultNotice tone="neutral">
          This experiment does not have any metrics yet.
        </ExperimentResultNotice>
      ) : (
        visibleMetrics.map((metric) => (
          <ExperimentMetricResult
            key={metric.id}
            metric={metric}
            display={display}
            showStatistics={expanded}
          />
        ))
      )}
      {display === "compact" && metrics.length > 0 && (
        <Button
          variant="link-muted"
          size="xs"
          className="self-start"
          data-attr="experiment-results-toggle-details"
          aria-expanded={expanded}
          onClick={() => setExpanded((isExpanded) => !isExpanded)}
        >
          {expanded
            ? "Hide result details"
            : hiddenMetricCount > 0
              ? `Show all ${metrics.length} metrics and statistics`
              : "Show statistics"}
        </Button>
      )}
    </div>
  );
}
