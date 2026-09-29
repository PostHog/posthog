import { ArrowSquareOutIcon, TargetIcon } from "@phosphor-icons/react";
import {
  impactMeasurementDecisionRule,
  impactMeasurementGoalLabel,
  selectImpactMeasurementPlans,
} from "@posthog/core/inbox/impactMeasurementPlans";
import { Button } from "@posthog/quill";
import { SIGNALS_EXPECTED_IMPACT_DISPLAY_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import type { ImpactMeasurementPlanArtefact } from "@posthog/shared/types";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { ReportChartCard } from "@posthog/ui/features/inbox/components/detail/ReportChartCard";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { inboxReportUrl } from "@posthog/ui/utils/posthogLinks";
import { useEffect, useMemo } from "react";

function MeasurementPlan({
  reportId,
  artefact,
}: {
  reportId: string;
  artefact: ImpactMeasurementPlanArtefact;
}) {
  const plan = artefact.content;
  const goal = impactMeasurementGoalLabel(plan);
  const decisionRule = impactMeasurementDecisionRule(plan);
  const grain =
    plan.goal_grain === "per_interval"
      ? "Goal per chart interval"
      : "Goal for the full query window";

  return (
    <div className="flex flex-col gap-2" data-testid="impact-measurement-plan">
      <div className="flex flex-col gap-0.5">
        <span className="font-semibold text-foreground text-xs">
          {plan.title}: {goal ?? "goal unavailable"}
        </span>
        <span className="text-muted-foreground text-xs">
          {plan.activated ? "Saved measurement" : "Proposed measurement"} ·{" "}
          {grain}
        </span>
      </div>
      {plan.query ? (
        <ReportChartCard
          reportId={reportId}
          chart={{
            // Each version has its own query, so key the result by version.
            chart_id: `impact-${artefact.id}`,
            title: plan.title,
            query: plan.query,
          }}
        />
      ) : (
        <p className="m-0 text-muted-foreground text-xs">
          The query is not available to you.
        </p>
      )}
      {decisionRule && (
        <p className="m-0 text-foreground text-xs">
          Suggested decision: {decisionRule}.
        </p>
      )}
    </div>
  );
}

/**
 * The report's proposed impact measurements: target, live query result, and
 * decision rule. Saving a proposal needs a signed-in browser session on the
 * backend, so the action opens the report in PostHog.
 */
export function ReportExpectedImpactSection({
  reportId,
}: {
  reportId: string;
}) {
  const enabled = useFeatureFlag(SIGNALS_EXPECTED_IMPACT_DISPLAY_FLAG);
  const { data } = useInboxReportArtefacts(reportId, { enabled });
  const plans = useMemo(
    () => selectImpactMeasurementPlans(data?.results ?? []),
    [data],
  );
  const pendingCount = plans.filter(
    (artefact) => artefact.content.query && !artefact.content.activated,
  ).length;
  const webUrl = inboxReportUrl(reportId);
  const hasPlans = enabled && plans.length > 0;

  // biome-ignore lint/correctness/useExhaustiveDependencies: count one view per report, not per refetch.
  useEffect(() => {
    if (!hasPlans) return;
    track(ANALYTICS_EVENTS.INBOX_EXPECTED_IMPACT_VIEWED, {
      report_id: reportId,
      plan_count: plans.length,
      pending_count: pendingCount,
    });
  }, [reportId, hasPlans]);

  if (!hasPlans) return null;

  return (
    <DetailSection Icon={TargetIcon} title="Expected impact">
      <div className="flex flex-col gap-4">
        {plans.map((artefact) => (
          <MeasurementPlan
            key={artefact.content.metric_id}
            reportId={reportId}
            artefact={artefact}
          />
        ))}
        {pendingCount > 0 && webUrl && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-attr="report-expected-impact-open-web"
              onClick={() => {
                track(ANALYTICS_EVENTS.INBOX_EXPECTED_IMPACT_OPENED_IN_WEB, {
                  report_id: reportId,
                  plan_count: plans.length,
                  pending_count: pendingCount,
                });
                openExternalUrl(webUrl);
              }}
            >
              <ArrowSquareOutIcon size={12} />
              Save in PostHog
            </Button>
            <span className="text-muted-foreground text-xs">
              You save proposed measurements in PostHog on the web.
            </span>
          </div>
        )}
      </div>
    </DetailSection>
  );
}
