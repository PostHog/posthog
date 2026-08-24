import {
  ArrowSquareOutIcon,
  ChatCircleIcon,
  CopyIcon,
  DotsThreeIcon,
  ReceiptIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
  Spinner,
  Textarea,
} from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import { useTaskChannels } from "@posthog/ui/features/canvas/hooks/useTaskChannels";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { RefundReportDialog } from "@posthog/ui/features/inbox/components/RefundReportDialog";
import { useCreateCanvasReport } from "@posthog/ui/features/inbox/hooks/useCreateCanvasReport";
import { useRefundReport } from "@posthog/ui/features/inbox/hooks/useRefundReport";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { useCallback, useState } from "react";

interface ReportDetailActionsProps {
  report: SignalReport;
  /** Implementation PR URL, when there is one; enables "Open in GitHub". */
  prUrl?: string | null;
}

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

/**
 * The report header's action cluster: Discuss and Canvas stay visible, and
 * everything occasional (GitHub, copy link, refund) folds into an overflow
 * menu. Discuss opens the report's chat dock rather than navigating away;
 * starting or continuing implementation work lives in the verdict banner
 * above the summary (ReportVerdictBanner / PrDecisionBlock), not here.
 */
export function ReportDetailActions({
  report,
  prUrl,
}: ReportDetailActionsProps) {
  // Resolved reports are terminal (their PR already merged), so the work actions
  // drop out; only the read-only overflow menu (copy link, PR link) stays.
  const isResolved = report.status === "resolved";

  const fireAction = useReportActionTracker(report);
  const chatOpen = useReportChatPanelStore((s) => s.open);
  const setChatOpen = useReportChatPanelStore((s) => s.setOpen);

  const handleToggleChat = useCallback(() => {
    if (!chatOpen) fireAction("discuss", { has_question: false });
    setChatOpen(!chatOpen);
  }, [chatOpen, setChatOpen, fireAction]);

  // Canvases started from a report file into the report's space, or #general
  // when the report has none — a task without a channel shows in no space's
  // sidebar at all.
  const { generalChannel, isLoading: channelsLoading } = useTaskChannels();
  const taskChannelId = report.channel_id ?? generalChannel?.id ?? null;
  // Until the channels query settles, an unassigned report has no fallback
  // channel yet — creating a task then would file it into no space at all.
  const awaitingChannel = taskChannelId === null && channelsLoading;

  const canvasActionEnabled = useChannelReportsEnabled();
  const { createCanvasReport, isCreatingCanvas } = useCreateCanvasReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    channelId: taskChannelId,
    cloudRepository: null,
  });

  // implementation_pr_url comes from raw task-run output; only a verified
  // GitHub PR URL may be opened or labeled as GitHub.
  const safePrUrl = prUrl && parsePrUrl(prUrl) ? prUrl : null;
  const refund = useRefundReport(report);
  const [refundOpen, setRefundOpen] = useState(false);

  const [canvasOpen, setCanvasOpen] = useState(false);
  const [canvasDirection, setCanvasDirection] = useState("");

  const handleCreateCanvas = useCallback(() => {
    const trimmed = canvasDirection.trim();
    fireAction("create_canvas", { has_feedback: trimmed.length > 0 });
    setCanvasDirection("");
    setCanvasOpen(false);
    void createCanvasReport(trimmed || undefined);
  }, [canvasDirection, createCanvasReport, fireAction]);

  // Read-only conveniences plus Refund. These are the only occasional actions,
  // and the read-only ones stay even on a resolved report; Refund is a mutation,
  // so it's gated out below.
  const overflowMenu = (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label="More report actions"
          >
            <DotsThreeIcon size={14} weight="bold" />
          </Button>
        }
      />
      <DropdownMenuContent align="end" side="bottom" sideOffset={6}>
        {safePrUrl && (
          <DropdownMenuItem
            onClick={() => window.open(safePrUrl, "_blank", "noopener")}
          >
            <ArrowSquareOutIcon size={13} />
            Open in GitHub
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onClick={() => copyInboxReportLink(report)}>
          <CopyIcon size={13} />
          Copy link
        </DropdownMenuItem>
        {refund.canRefund && !isResolved && (
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

  // A terminal report keeps only the read-only overflow menu.
  if (isResolved) {
    return overflowMenu;
  }

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-pressed={chatOpen}
        className="gap-1"
        onClick={handleToggleChat}
        title="Chat with the agent about this report"
      >
        <ChatCircleIcon size={12} />
        Chat with this report
      </Button>

      {canvasActionEnabled && (
        <Popover
          open={canvasOpen}
          onOpenChange={(next) => {
            setCanvasOpen(next);
            if (!next) setCanvasDirection("");
          }}
        >
          <PopoverTrigger
            render={
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isCreatingCanvas || awaitingChannel}
                className="gap-1"
                title="Have the agent build a canvas from this report"
              >
                {isCreatingCanvas ? <Spinner /> : <ShapesIcon size={12} />}
                Create canvas…
              </Button>
            }
          />
          <PopoverContent
            align="end"
            side="bottom"
            sideOffset={6}
            className="flex w-[420px] flex-col gap-2 p-3"
          >
            <span className="text-[12px] text-gray-11">
              What should the canvas focus on? The agent builds it from this
              report's evidence and live data.
            </span>
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
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-gray-10">
                {isMac ? "⌘↵" : "Ctrl+↵"} to create
              </span>
              <Button
                type="button"
                variant="primary"
                size="sm"
                disabled={isCreatingCanvas || awaitingChannel}
                onClick={handleCreateCanvas}
              >
                Create canvas
              </Button>
            </div>
          </PopoverContent>
        </Popover>
      )}

      {/* An overflow menu earns its click only with something to hide; when
          Copy link is the lone occasional action, it shows directly. */}
      {!prUrl && !refund.canRefund ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-label="Copy link to this report"
          title="Copy link to this report"
          onClick={() => copyInboxReportLink(report)}
        >
          <CopyIcon size={13} />
        </Button>
      ) : (
        overflowMenu
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
    </>
  );
}
