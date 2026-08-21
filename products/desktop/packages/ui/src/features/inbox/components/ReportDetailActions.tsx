import {
  ArrowSquareOutIcon,
  ChatCircleIcon,
  CopyIcon,
  DotsThreeIcon,
  ReceiptIcon,
  ShapesIcon,
} from "@phosphor-icons/react";
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
import { useDiscussReport } from "@posthog/ui/features/inbox/hooks/useDiscussReport";
import { useRefundReport } from "@posthog/ui/features/inbox/hooks/useRefundReport";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
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
 * menu. Starting or continuing implementation work lives in the verdict
 * banner above the summary (ReportVerdictBanner / PrDecisionBlock), not here.
 */
export function ReportDetailActions({
  report,
  prUrl,
}: ReportDetailActionsProps) {
  // Resolved reports are terminal — their PR already merged, so no actions apply.
  const isResolved = report.status === "resolved";

  const fireAction = useReportActionTracker(report);
  // Sessions and canvases started from a report file into the report's space,
  // or #general when the report has none — a task without a channel shows in
  // no space's sidebar at all.
  const { generalChannel } = useTaskChannels();
  const taskChannelId = report.channel_id ?? generalChannel?.id ?? null;
  const { discussReport, isDiscussing } = useDiscussReport({
    report,
    channelId: taskChannelId,
  });

  const canvasActionEnabled = useChannelReportsEnabled();
  const { createCanvasReport, isCreatingCanvas } = useCreateCanvasReport({
    reportId: report.id,
    reportTitle: report.title ?? null,
    channelId: taskChannelId,
    cloudRepository: null,
  });

  const refund = useRefundReport(report);
  const [refundOpen, setRefundOpen] = useState(false);

  const handleCreateCanvas = useCallback(() => {
    fireAction("create_canvas");
    void createCanvasReport();
  }, [createCanvasReport, fireAction]);

  const [discussQuestion, setDiscussQuestion] = useState("");
  const [discussOpen, setDiscussOpen] = useState(false);

  const submitDiscuss = useCallback(() => {
    const trimmed = discussQuestion.trim();
    if (!trimmed) return;
    fireAction("discuss", {
      has_question: true,
      question_text: trimmed.slice(0, 500),
    });
    setDiscussQuestion("");
    setDiscussOpen(false);
    void discussReport(trimmed);
  }, [discussQuestion, discussReport, fireAction]);

  const submitDisabled = discussQuestion.trim().length === 0 || isDiscussing;

  if (isResolved) {
    return null;
  }

  return (
    <>
      <Popover
        open={discussOpen}
        onOpenChange={(next) => {
          setDiscussOpen(next);
          if (!next) setDiscussQuestion("");
        }}
      >
        <PopoverTrigger
          render={
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={isDiscussing}
              className="gap-1"
              title="Discuss this report with your agent"
            >
              {isDiscussing ? <Spinner /> : <ChatCircleIcon size={12} />}
              Discuss
            </Button>
          }
        />
        <PopoverContent
          align="end"
          side="bottom"
          sideOffset={6}
          className="w-[420px] p-3"
        >
          <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              submitDiscuss();
            }}
          >
            <Textarea
              aria-label="Question to discuss with the agent"
              autoFocus
              placeholder="Ask about this report…"
              rows={5}
              value={discussQuestion}
              onChange={(event) => setDiscussQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                  event.preventDefault();
                  submitDiscuss();
                }
              }}
            />
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] text-gray-10">
                {isMac ? "⌘↵" : "Ctrl+↵"} to send
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setDiscussOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  disabled={submitDisabled}
                >
                  Discuss
                </Button>
              </div>
            </div>
          </form>
        </PopoverContent>
      </Popover>

      {canvasActionEnabled && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={isCreatingCanvas}
          className="gap-1"
          onClick={handleCreateCanvas}
          title="Have your agent build a canvas from this report"
        >
          {isCreatingCanvas ? <Spinner /> : <ShapesIcon size={12} />}
          Canvas
        </Button>
      )}

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
          {prUrl && (
            <DropdownMenuItem
              onClick={() => window.open(prUrl, "_blank", "noopener")}
            >
              <ArrowSquareOutIcon size={13} />
              Open in GitHub
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => copyInboxReportLink(report)}>
            <CopyIcon size={13} />
            Copy link
          </DropdownMenuItem>
          {refund.canRefund && (
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
