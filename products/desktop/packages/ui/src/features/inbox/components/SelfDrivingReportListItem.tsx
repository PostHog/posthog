import { GitMergeIcon, GitPullRequestIcon } from "@phosphor-icons/react";
import {
  deriveHeadline,
  describeReportPr,
  humanizeReportTitle,
} from "@posthog/core/inbox/reportPresentation";
import { cn } from "@posthog/quill";
import { formatRelativeAge } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { RailListItem } from "@posthog/ui/features/sidebar/components/RailListItem";
import type { ComponentProps, ReactElement, ReactNode } from "react";

type RailPointerHandlers = Pick<
  ComponentProps<typeof RailListItem>,
  "onFocus" | "onPointerDown" | "onPointerEnter"
>;

interface SelfDrivingReportListItemProps extends RailPointerHandlers {
  report: SignalReport;
  isSelected?: boolean;
  compact?: boolean;
  asOption?: boolean;
  optionValue?: string;
  emphasized?: boolean;
  /** Names the row a Self-driving report, for a list that mixes item kinds. */
  showKind?: boolean;
  /** Which timestamp the age reads from; match the list's grouping or sort. */
  ageFrom?: "created_at" | "updated_at";
  actions?: ReactNode;
  actionCount?: number;
  actionsVisibility?: "hover" | "always";
  onClick: () => void;
  loading?: boolean;
  disabled?: boolean;
}

export function SelfDrivingReportListItem({
  report,
  isSelected,
  compact,
  asOption,
  optionValue,
  emphasized,
  showKind,
  ageFrom = "created_at",
  actions,
  actionCount,
  actionsVisibility,
  onClick,
  loading,
  disabled,
  ...pointerHandlers
}: SelfDrivingReportListItemProps): ReactElement {
  const title = humanizeReportTitle(report.title, "Untitled report");
  const detail = deriveHeadline(report.summary) ?? undefined;
  const reportPr = describeReportPr(report);
  const stateSuffix =
    reportPr?.state === "draft"
      ? " draft"
      : reportPr?.state === "merged"
        ? " merged"
        : reportPr?.state === "shipped"
          ? " shipped"
          : "";
  const prToneClass =
    reportPr?.state === "shipped"
      ? "text-green-11"
      : reportPr?.state === "open"
        ? "text-(--accent-11)"
        : undefined;

  return (
    <RailListItem
      leading={<PriorityMonogram priority={report.priority} size="small" />}
      title={title}
      meta={
        <>
          <span className="truncate">
            {formatRelativeAge(report[ageFrom])}
            {showKind && " · Self-driving"}
          </span>
          <span aria-hidden>·</span>
          {reportPr ? (
            <span
              className={cn(
                "inline-flex shrink-0 items-center gap-0.5",
                prToneClass,
              )}
            >
              {reportPr.state === "merged" || reportPr.state === "shipped" ? (
                <GitMergeIcon size={11} />
              ) : (
                <GitPullRequestIcon size={11} />
              )}
              #{reportPr.pr.number}
              {stateSuffix}
              <span className="@sm/rail:inline hidden">
                {" · "}
                {reportPr.pr.repoSlug}
              </span>
            </span>
          ) : (
            <span className="shrink-0">No PR</span>
          )}
        </>
      }
      detail={detail}
      detailLines={2}
      isSelected={isSelected}
      compact={compact}
      asOption={asOption}
      optionValue={optionValue}
      emphasized={emphasized}
      actions={actions}
      actionCount={actionCount}
      actionsVisibility={actionsVisibility}
      onClick={onClick}
      loading={loading}
      disabled={disabled}
      aria-label={`${title}, priority ${report.priority ?? "unknown"}${showKind ? ", Self-driving report" : ""}`}
      {...pointerHandlers}
    />
  );
}
