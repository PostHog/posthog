import {
  ArrowCounterClockwiseIcon,
  CheckCircleIcon,
  CopyIcon,
  EyeSlashIcon,
  GitPullRequestIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import { extractRepoSelectionRepository } from "@posthog/core/inbox/artefacts";
import {
  canCreateImplementationPr,
  canResolveReport,
} from "@posthog/core/inbox/reportActions";
import {
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
} from "@posthog/quill";
import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
  isDismissalReasonSnooze,
  RESOLVE_REASON_OPTIONS,
  type ResolveReasonOptionValue,
} from "@posthog/shared/dismissalReasons";
import type { SignalReport } from "@posthog/shared/types";
import { ReviewerSearchList } from "@posthog/ui/features/inbox/components/ReviewerSearchList";
import { useCreatePrReport } from "@posthog/ui/features/inbox/hooks/useCreatePrReport";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportResolveAction } from "@posthog/ui/features/inbox/hooks/useInboxReportResolveAction";
import { useInboxReportArtefacts } from "@posthog/ui/features/inbox/hooks/useInboxReports";
import { useInboxRestoreReport } from "@posthog/ui/features/inbox/hooks/useInboxRestoreReport";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import {
  findContinuableImplementationTask,
  useReportTasks,
} from "@posthog/ui/features/inbox/hooks/useReportTasks";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { Fragment, useRef, useState } from "react";

export function InboxReportContextMenuContent({
  report,
  open,
}: {
  report: SignalReport;
  open: boolean;
}): React.JSX.Element {
  const [reviewersOpen, setReviewersOpen] = useState(false);
  const openedDialogRef = useRef(false);
  const fireAction = useReportActionTracker(report, "context_menu");
  const resolve = useInboxReportResolveAction(report, "context_menu");
  const dismiss = useInboxReportDismissAction(report, "context_menu");
  const restore = useInboxRestoreReport();
  const { data: artefacts } = useInboxReportArtefacts(report.id, {
    enabled: open,
  });
  const {
    data: reportTasks,
    isLoading: reportTasksLoading,
    isError: reportTasksFailed,
  } = useReportTasks(report.id, report.status);
  const continuableTask = findContinuableImplementationTask(reportTasks);
  const cloudRepository = extractRepoSelectionRepository(artefacts?.results);
  const { createPrReport, isCreatingPr } = useCreatePrReport({
    reportId: report.id,
    reportTitle: report.title,
    cloudRepository,
    surface: "context_menu",
  });

  const isDismissed = report.status === "suppressed";
  const hasOpenPr =
    Boolean(report.implementation_pr_url) &&
    report.implementation_pr_merged !== true;
  const canCreatePr = canCreateImplementationPr(report, {
    hasLiveImplementationTask: continuableTask !== null,
    isTaskLookupPending: reportTasksLoading || reportTasksFailed,
  });

  const openResolveDialog = (reason: ResolveReasonOptionValue): void => {
    openedDialogRef.current = true;
    resolve.openDialog(reason);
  };
  const pickResolveReason = (reason: ResolveReasonOptionValue): void => {
    if (reason === "other" || hasOpenPr) {
      openResolveDialog(reason);
      return;
    }
    resolve.resolveWithReason(reason);
  };
  const openDismissDialog = (reason: DismissalReasonOptionValue): void => {
    openedDialogRef.current = true;
    dismiss.openDialog(reason);
  };
  const pickDismissReason = (reason: DismissalReasonOptionValue): void => {
    if (reason === "other" || hasOpenPr || isDismissalReasonSnooze(reason)) {
      openDismissDialog(reason);
      return;
    }
    void dismiss.dismissWithReason(reason);
  };

  return (
    <>
      <ContextMenuContent
        className="min-w-48"
        finalFocus={() => {
          if (openedDialogRef.current) {
            openedDialogRef.current = false;
            return false;
          }
          return undefined;
        }}
      >
        {isDismissed ? (
          <ContextMenuGroup>
            <ContextMenuItem
              disabled={restore.isPending}
              onClick={() => {
                fireAction("restore");
                restore.mutate(report.id);
              }}
            >
              <ArrowCounterClockwiseIcon size={14} />
              Restore
            </ContextMenuItem>
          </ContextMenuGroup>
        ) : (
          <ContextMenuGroup>
            {canCreatePr ? (
              <>
                <ContextMenuItem
                  disabled={isCreatingPr}
                  onClick={() => {
                    fireAction("create_pr", { has_feedback: false });
                    void createPrReport();
                  }}
                >
                  <GitPullRequestIcon size={14} />
                  Create PR
                </ContextMenuItem>
                <ContextMenuSeparator />
              </>
            ) : null}
            {canResolveReport(report) ? (
              <ContextMenuSub>
                <ContextMenuSubTrigger disabled={resolve.isPending} openOnHover>
                  <CheckCircleIcon size={14} />
                  Resolve
                </ContextMenuSubTrigger>
                <ContextMenuSubContent className="max-w-80">
                  <ContextMenuGroup>
                    {RESOLVE_REASON_OPTIONS.map((option) => (
                      <Fragment key={option.value}>
                        {option.value === "other" ? (
                          <ContextMenuSeparator />
                        ) : null}
                        <ContextMenuItem
                          disabled={resolve.isPending}
                          onClick={() => pickResolveReason(option.value)}
                        >
                          {option.label}
                        </ContextMenuItem>
                      </Fragment>
                    ))}
                  </ContextMenuGroup>
                </ContextMenuSubContent>
              </ContextMenuSub>
            ) : null}
            <ContextMenuSub>
              <ContextMenuSubTrigger openOnHover>
                <EyeSlashIcon size={14} />
                Dismiss
              </ContextMenuSubTrigger>
              <ContextMenuSubContent className="max-w-80">
                <ContextMenuGroup>
                  {DISMISSAL_REASON_OPTIONS.map((option) => (
                    <Fragment key={option.value}>
                      {option.value === "other" ? (
                        <ContextMenuSeparator />
                      ) : null}
                      <ContextMenuItem
                        onClick={() => pickDismissReason(option.value)}
                      >
                        {option.label}
                      </ContextMenuItem>
                    </Fragment>
                  ))}
                </ContextMenuGroup>
              </ContextMenuSubContent>
            </ContextMenuSub>
            <ContextMenuSub onOpenChange={setReviewersOpen}>
              <ContextMenuSubTrigger openOnHover>
                <UsersThreeIcon size={14} />
                Reviewers
              </ContextMenuSubTrigger>
              <ContextMenuSubContent className="max-w-none p-0">
                <ReviewerSearchList
                  report={report}
                  surface="context_menu"
                  enabled={reviewersOpen}
                />
              </ContextMenuSubContent>
            </ContextMenuSub>
          </ContextMenuGroup>
        )}
        <ContextMenuSeparator />
        <ContextMenuGroup>
          <ContextMenuItem
            onClick={() => {
              fireAction("copy_link");
              copyInboxReportLink(report);
            }}
          >
            <CopyIcon size={14} />
            Copy link
          </ContextMenuItem>
        </ContextMenuGroup>
      </ContextMenuContent>
      {resolve.dialog}
      {dismiss.dialog}
    </>
  );
}
