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
  ContextMenu,
  ContextMenuContent,
  ContextMenuGroup,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from "@posthog/quill";
import {
  DISMISSAL_REASON_OPTIONS,
  type DismissalReasonOptionValue,
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
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { Fragment, type ReactNode, useRef, useState } from "react";

export function InboxReportContextMenu({
  report,
  children,
}: {
  report: SignalReport;
  children: ReactNode;
}): React.JSX.Element {
  const [open, setOpen] = useState(false);
  const [reviewersOpen, setReviewersOpen] = useState(false);
  const openedDialogRef = useRef(false);
  const fireAction = useReportActionTracker(report, "context_menu");
  const resolve = useInboxReportResolveAction(report, "context_menu");
  const dismiss = useInboxReportDismissAction(report, "context_menu");
  const restore = useInboxRestoreReport();
  const { data: artefacts } = useInboxReportArtefacts(report.id, {
    enabled: open,
  });
  const cloudRepository = extractRepoSelectionRepository(artefacts?.results);
  const { createPrReport, isCreatingPr } = useCreatePrReport({
    reportId: report.id,
    reportTitle: report.title,
    cloudRepository,
  });

  const isDismissed = report.status === "suppressed";
  const hasOpenPr =
    Boolean(report.implementation_pr_url) &&
    report.implementation_pr_merged !== true;
  const hasMenu =
    report.status !== "resolved" && !(isDismissed && report.refund != null);

  if (!hasMenu) return <>{children}</>;

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
    if (reason === "other" || hasOpenPr) {
      openDismissDialog(reason);
      return;
    }
    void dismiss.dismissWithReason(reason);
  };
  const copyLinkItem = (
    <>
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
    </>
  );

  return (
    <>
      <ContextMenu
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setReviewersOpen(false);
        }}
      >
        <ContextMenuTrigger render={<div className="min-w-0" />}>
          {children}
        </ContextMenuTrigger>
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
                  // Fire before the mutation: restore removes the row from the
                  // list, unmounting this menu (and its mutation observer)
                  // before a per-call onSuccess would run, which drops the event.
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
              {canCreateImplementationPr(report) && (
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
              )}
              {canResolveReport(report) && (
                <ContextMenuSub>
                  <ContextMenuSubTrigger>
                    <CheckCircleIcon size={14} />
                    Resolve
                  </ContextMenuSubTrigger>
                  <ContextMenuSubContent className="max-w-80">
                    <ContextMenuGroup>
                      {RESOLVE_REASON_OPTIONS.map((option) => (
                        <Fragment key={option.value}>
                          {option.value === "other" && <ContextMenuSeparator />}
                          <ContextMenuItem
                            onClick={() => pickResolveReason(option.value)}
                          >
                            {option.label}
                          </ContextMenuItem>
                        </Fragment>
                      ))}
                    </ContextMenuGroup>
                  </ContextMenuSubContent>
                </ContextMenuSub>
              )}
              <ContextMenuSub>
                <ContextMenuSubTrigger>
                  <EyeSlashIcon size={14} />
                  Dismiss
                </ContextMenuSubTrigger>
                <ContextMenuSubContent className="max-w-80">
                  <ContextMenuGroup>
                    {DISMISSAL_REASON_OPTIONS.map((option) => (
                      <Fragment key={option.value}>
                        {option.value === "other" && <ContextMenuSeparator />}
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
                <ContextMenuSubTrigger>
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
          {copyLinkItem}
        </ContextMenuContent>
      </ContextMenu>
      {resolve.dialog}
      {dismiss.dialog}
    </>
  );
}
