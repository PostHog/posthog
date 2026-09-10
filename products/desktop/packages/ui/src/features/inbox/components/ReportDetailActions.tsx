import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  DotsThreeIcon,
  EyeSlashIcon,
  LinkIcon,
  ReceiptIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import { canResolveReport } from "@posthog/core/inbox/reportActions";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  Textarea,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { RefundReportDialog } from "@posthog/ui/features/inbox/components/RefundReportDialog";
import { ReportChatToggle } from "@posthog/ui/features/inbox/components/ReportChatToggle";
import { useCreateCanvasReport } from "@posthog/ui/features/inbox/hooks/useCreateCanvasReport";
import { useInboxReportDismissAction } from "@posthog/ui/features/inbox/hooks/useInboxReportDismissAction";
import { useInboxReportResolveAction } from "@posthog/ui/features/inbox/hooks/useInboxReportResolveAction";
import { useRefundReport } from "@posthog/ui/features/inbox/hooks/useRefundReport";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useCallback, useState } from "react";

interface ReportDetailActionsProps {
  report: SignalReport;
  /** Explicit PR URL (the PR-tab detail passes its own); falls back to the report's. */
  prUrl?: string | null;
  placement?: "standalone" | "header";
}

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

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

  const fireAction = useReportActionTracker(report);
  const setChatOpen = useReportChatPanelStore((s) => s.setOpen);

  // Canvases started from a report file into the report's space, or #general
  // when the report has none — a task without a channel shows in no space's
  // sidebar at all.
  const { generalChannel, isLoading: channelsLoading } = useTaskChannels();
  const taskChannelId = report.channel_id ?? generalChannel?.id ?? null;
  // Until the channels query settles, an unassigned report has no fallback
  // channel yet — creating a task then would file it into no space at all.
  const awaitingChannel = taskChannelId === null && channelsLoading;

  const canvasActionEnabled = useChannelReportsEnabled();
  const rememberStartedTask = useReportChatPanelStore(
    (s) => s.rememberStartedTask,
  );
  const handleCanvasTaskCreated = useCallback(
    (task: { id: string }) => {
      rememberStartedTask(report.id, task.id);
      setChatOpen(true);
    },
    [rememberStartedTask, report.id, setChatOpen],
  );
  const { createCanvasReport, isCreatingCanvas } = useCreateCanvasReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    channelId: taskChannelId,
    cloudRepository: null,
    onTaskCreated: handleCanvasTaskCreated,
  });

  // implementation_pr_url comes from raw task-run output; only a verified
  // GitHub PR URL may be opened or labeled as GitHub.
  const safePrUrl = prUrl && parsePrUrl(prUrl) ? prUrl : null;
  const refund = useRefundReport(report);
  const [refundOpen, setRefundOpen] = useState(false);
  const dismiss = useInboxReportDismissAction(report);
  const resolve = useInboxReportResolveAction(report);

  const [canvasOpen, setCanvasOpen] = useState(false);
  const [canvasDirection, setCanvasDirection] = useState("");

  const handleCreateCanvas = useCallback(() => {
    if (isCreatingCanvas || awaitingChannel) return;
    const trimmed = canvasDirection.trim();
    fireAction("create_canvas", { has_feedback: trimmed.length > 0 });
    setCanvasDirection("");
    setCanvasOpen(false);
    void createCanvasReport(trimmed || undefined);
  }, [
    canvasDirection,
    createCanvasReport,
    fireAction,
    isCreatingCanvas,
    awaitingChannel,
  ]);

  const canvasDialog = canvasActionEnabled && !isResolved && (
    <Dialog
      open={canvasOpen}
      onOpenChange={(next) => {
        setCanvasOpen(next);
        if (!next) setCanvasDirection("");
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Visualize on a canvas</DialogTitle>
          <DialogDescription>
            What should the canvas focus on? The agent builds it from this
            report's evidence and live data.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <Textarea
            aria-label="What the canvas should focus on"
            autoFocus
            placeholder="Focus on… (optional)"
            rows={3}
            value={canvasDirection}
            onChange={(event) => setCanvasDirection(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                handleCreateCanvas();
              }
            }}
          />
        </DialogBody>
        <DialogFooter>
          <span className="mr-auto text-[12px] text-gray-10">
            {isMac ? "⌘↵" : "Ctrl+↵"} to create
          </span>
          <Button
            type="button"
            variant="primary"
            loading={isCreatingCanvas}
            disabled={isCreatingCanvas || awaitingChannel}
            onClick={handleCreateCanvas}
          >
            Create canvas
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );

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
        {canvasActionEnabled && !isResolved && (
          <DropdownMenuItem
            disabled={isCreatingCanvas || awaitingChannel}
            onClick={() => setCanvasOpen(true)}
          >
            <ShapesIcon />
            Visualize on a canvas…
          </DropdownMenuItem>
        )}
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
        Open PR
      </Button>
    ) : (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => openExternalUrl(safePrUrl)}
      >
        <ArrowSquareOutIcon size={16} />
        Open PR in GitHub
      </Button>
    )
  ) : null;

  if (placement === "header") {
    return (
      <>
        <ReportChatToggle report={report} />
        {githubButton}
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
        {canvasDialog}
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

      {canvasActionEnabled && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isCreatingCanvas || awaitingChannel}
          onClick={() => setCanvasOpen(true)}
        >
          <ShapesIcon />
          Visualize on a canvas
        </Button>
      )}
      {canvasDialog}

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
