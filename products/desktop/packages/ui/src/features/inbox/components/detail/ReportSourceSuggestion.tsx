import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { reportAgeHours } from "@posthog/core/inbox/engagement";
import { sourceSuggestionTarget } from "@posthog/core/inbox/sourceSuggestion";
import { Button } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type {
  SignalReport,
  SignalReportSourceSuggestion,
} from "@posthog/shared/types";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { projectPathUrl } from "@posthog/ui/utils/posthogLinks";
import { useEffect } from "react";

function suggestionEventProperties(report: SignalReport, product: string) {
  return {
    report_id: report.id,
    report_age_hours: reportAgeHours(report.created_at),
    priority: report.priority ?? null,
    actionability: report.actionability ?? null,
    has_pr: !!report.implementation_pr_url,
    product,
  };
}

/**
 * A product the team doesn't use that would have given this report better
 * evidence, shown after the evidence with a link to the product in PostHog.
 */
export function ReportSourceSuggestion({
  report,
  suggestion,
}: {
  report: SignalReport;
  suggestion: SignalReportSourceSuggestion;
}) {
  const target = sourceSuggestionTarget(suggestion.product);
  const url = target ? projectPathUrl(target.path) : null;
  const shown = url !== null;

  // biome-ignore lint/correctness/useExhaustiveDependencies: once per report and product, not on every report refetch.
  useEffect(() => {
    if (shown) {
      track(
        ANALYTICS_EVENTS.INBOX_REPORT_SOURCE_SUGGESTION_SHOWN,
        suggestionEventProperties(report, suggestion.product),
      );
    }
  }, [shown, report.id, suggestion.product]);

  if (!target || !url) return null;

  return (
    <ReportSourceSuggestionView
      product={suggestion.product}
      reason={suggestion.reason}
      actionLabel={target.actionLabel}
      onOpen={() => {
        track(
          ANALYTICS_EVENTS.INBOX_REPORT_SOURCE_SUGGESTION_CLICKED,
          suggestionEventProperties(report, suggestion.product),
        );
        openExternalUrl(url);
      }}
    />
  );
}

export function ReportSourceSuggestionView({
  product,
  reason,
  actionLabel,
  onOpen,
}: {
  product: string;
  reason: string;
  actionLabel: string;
  onOpen: () => void;
}) {
  const meta = getSourceProductMeta(product);

  return (
    <div className="flex flex-col gap-2 rounded-md border border-border border-dashed p-3">
      <div className="flex items-center gap-1.5 text-muted-foreground text-xs">
        {meta && (
          <meta.Icon
            size={13}
            className="shrink-0"
            style={{ color: meta.color }}
          />
        )}
        <span className="font-medium">{meta?.label ?? product}</span>
        <span>· Not set up in this project</span>
      </div>
      <p className="m-0 text-foreground text-xs">{reason}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="self-start"
        onClick={onOpen}
      >
        <ArrowSquareOutIcon size={12} />
        {actionLabel}
      </Button>
    </div>
  );
}
