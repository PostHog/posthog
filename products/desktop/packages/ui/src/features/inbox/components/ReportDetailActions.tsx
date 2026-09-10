import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  DotsThreeIcon,
  EyeSlashIcon,
  LinkIcon,
  ReceiptIcon,
} from "@phosphor-icons/react";
import { canResolveReport } from "@posthog/core/inbox/reportActions";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { RefundReportDialog } from "@posthog/ui/features/inbox/components/RefundReportDialog";
import { ReportChatToggle } from "@posthog/ui/features/inbox/components/ReportChatToggle";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportResolveAction } from "@posthog/ui/features/inbox/hooks/useInboxReportResolveAction";
import { useRefundReport } from "@posthog/ui/features/inbox/hooks/useRefundReport";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useState } from "react";

interface ReportDetailActionsProps {
  report: SignalReport;
  /** Explicit PR URL (the PR-tab detail passes its own); falls back to the report's. */
  prUrl?: string | null;
  placement?: "standalone" | "header";
}

/** Report actions split between page-level housekeeping and conversation work. */
export function ReportDetailActions({
  report,
  prUrl: prUrlProp,
  placement = "standalone",
}: ReportDetailActionsProps) {
  // The report's own PR (open or merged) backs the GitHub item, so a merged
  // fix stays reachable from the page even after the banner demotes it to
  // history.
  const prUrl = prUrlProp ?? report.implementation_pr_url ?? null;
  // Resolved reports are terminal (their PR already merged), so the work actions
  // drop out; only the read-only overflow menu (copy link, PR link) stays.
  const isResolved = report.status === "resolved";

  // implementation_pr_url comes from raw task-run output; only a verified
  // GitHub PR URL may be opened or labeled as GitHub.
  const safePrUrl = prUrl && parsePrUrl(prUrl) ? prUrl : null;
  const refund = useRefundReport(report);
  const [refundOpen, setRefundOpen] = useState(false);
  const dismiss = useInboxReportDismissAction(report);
  const resolve = useInboxReportResolveAction(report);

  const overflowMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="icon-sm"
            aria-label="More report actions"
          >
            <DotsThreeIcon size={14} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent align="end" side="bottom" sideOffset={6}>
        <DropdownMenuSub>
          <DropdownMenuSubTrigger>
            <LinkIcon size={13} />
            Copy link
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent
            side="right"
            sideOffset={4}
            className="min-w-44"
          >
            <DropdownMenuItem
              data-attr="inbox-copy-web-link"
              onClick={() => copyInboxReportLink(report, "web")}
            >
              Copy web link
            </DropdownMenuItem>
            <DropdownMenuItem
              data-attr="inbox-copy-desktop-link"
              onClick={() => copyInboxReportLink(report, "desktop")}
            >
              Copy desktop link
            </DropdownMenuItem>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        {placement === "standalone" && refund.canRefund && !isResolved && (
          <DropdownMenuItem
            disabled={refund.disabledReason !== null}
            onClick={() => setRefundOpen(true)}
          >
            <ReceiptIcon size={13} />
            Refund…
          </DropdownMenuItem>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
  const githubButton = safePrUrl ? (
    placement === "header" ? (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => openExternalUrl(safePrUrl)}
      >
        <ArrowSquareOutIcon size={14} />
        Open in GitHub
      </Button>
    ) : (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => openExternalUrl(safePrUrl)}
      >
        <ArrowSquareOutIcon size={16} />
        Open in GitHub
      </Button>
    )
  ) : null;

  if (placement === "header") {
    return (
      <>
        {githubButton}
        <ReportChatToggle report={report} />
        {canResolveReport(report) && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            loading={resolve.isPending}
            disabled={resolve.isPending}
            data-attr="inbox-report-resolve"
            onClick={() => resolve.openDialog()}
          >
            <CheckCircleIcon size={14} />
            Resolve
          </Button>
        )}
        {!isResolved && report.status !== "suppressed" && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            data-attr="inbox-report-dismiss"
            onClick={() => dismiss.openDialog()}
          >
            <EyeSlashIcon size={14} />
            Dismiss
          </Button>
        )}
        {overflowMenu}
        {refund.canRefund && (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  aria-label="Refund"
                  disabled={refund.disabledReason !== null}
                  onClick={() => setRefundOpen(true)}
                />
              }
            >
              <ReceiptIcon />
              Refund
            </TooltipTrigger>
            <TooltipContent>
              {refund.disabledReason ?? "Refund this PR and archive the report"}
            </TooltipContent>
          </Tooltip>
        )}
        {refund.canRefund && (
          <RefundReportDialog
            open={refundOpen}
            onOpenChange={setRefundOpen}
            report={report}
            isSubmitting={refund.mutation.isPending}
            onConfirm={(input) =>
              refund.mutation.mutate(input, {
                onSuccess: () => setRefundOpen(false),
              })
            }
          />
        )}
        {resolve.dialog}
        {dismiss.dialog}
      </>
    );
  }

  // A terminal report keeps its read-only GitHub and overflow actions.
  if (isResolved) {
    return (
      <>
        {githubButton}
        {overflowMenu}
      </>
    );
  }

  return (
    <>
      {githubButton}

      {placement === "standalone" && overflowMenu}

      {placement === "standalone" && refund.canRefund && (
        <RefundReportDialog
          open={refundOpen}
          onOpenChange={setRefundOpen}
          report={report}
          isSubmitting={refund.mutation.isPending}
          onConfirm={(input) =>
            refund.mutation.mutate(input, {
              onSuccess: () => setRefundOpen(false),
            })
          }
        />
      )}
    </>
  );
}
