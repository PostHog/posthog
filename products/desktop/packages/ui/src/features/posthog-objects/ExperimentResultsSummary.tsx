import type { ExperimentResultsPresentation } from "@posthog/api-client/evidence-previews";
import { Accordion, Skeleton, Text } from "@posthog/quill";
import type { ReactElement } from "react";
import { ExperimentMetricResult } from "./ExperimentMetricResult";
import { ExperimentResultNotice } from "./ExperimentResultNotice";

export interface ExperimentResultsSummaryProps {
  display: "compact" | "full";
  loadState: "loading" | "error" | "missing" | "ready";
  results: ExperimentResultsPresentation | null | undefined;
}

const MAX_COMPACT_METRICS = 3;

export function ExperimentResultsSummary({
  display,
  loadState,
  results,
}: ExperimentResultsSummaryProps): ReactElement {
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

  const allMetrics = [...results.primaryMetrics, ...results.secondaryMetrics];
  const headlineMetrics =
    results.primaryMetrics.length > 0
      ? results.primaryMetrics
      : results.secondaryMetrics;
  const metrics = headlineMetrics.slice(0, MAX_COMPACT_METRICS);
  const hiddenMetricCount = allMetrics.length - metrics.length;

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
      {allMetrics.length === 0 ? (
        <ExperimentResultNotice tone="neutral">
          This experiment does not have any metrics yet.
        </ExperimentResultNotice>
      ) : display === "full" ? (
        <div className="flex flex-col gap-4">
          {results.primaryMetrics.length > 0 && (
            <section>
              <Text size="xs" weight="semibold" variant="muted">
                Primary metrics ({results.primaryMetrics.length})
              </Text>
              <Accordion
                multiple
                defaultValue={results.primaryMetrics.map((metric) => metric.id)}
              >
                {results.primaryMetrics.map((metric) => (
                  <ExperimentMetricResult
                    key={metric.id}
                    metric={metric}
                    display="full"
                  />
                ))}
              </Accordion>
            </section>
          )}
          {results.secondaryMetrics.length > 0 && (
            <section>
              <Text size="xs" weight="semibold" variant="muted">
                Secondary metrics ({results.secondaryMetrics.length})
              </Text>
              <Accordion multiple>
                {results.secondaryMetrics.map((metric) => (
                  <ExperimentMetricResult
                    key={metric.id}
                    metric={metric}
                    display="full"
                  />
                ))}
              </Accordion>
            </section>
          )}
        </div>
      ) : (
        <div className="divide-y divide-border overflow-hidden rounded-md border border-border bg-card">
          {metrics.map((metric) => (
            <ExperimentMetricResult
              key={metric.id}
              metric={metric}
              display="compact"
            />
          ))}
        </div>
      )}
      {display === "compact" && hiddenMetricCount > 0 && (
        <Text size="xxs" variant="muted">
          +{hiddenMetricCount} more metric
          {hiddenMetricCount === 1 ? "" : "s"} on the full page
        </Text>
      )}
    </div>
  );
}
