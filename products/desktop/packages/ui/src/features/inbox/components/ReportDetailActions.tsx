import {
  ArrowSquareOutIcon,
  ClockIcon,
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
import { useInboxBulkActions } from "@posthog/ui/features/inbox/hooks/useInboxBulkActions";
import { useRefundReport } from "@posthog/ui/features/inbox/hooks/useRefundReport";
import { useReportActionTracker } from "@posthog/ui/features/inbox/hooks/useReportActionTracker";
import { useReportChatPanelStore } from "@posthog/ui/features/inbox/stores/reportChatPanelStore";
import { copyInboxReportLink } from "@posthog/ui/features/inbox/utils/copyInboxReportLink";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { useCallback, useMemo, useState } from "react";

interface ReportDetailActionsProps {
  report: SignalReport;
  /** Explicit PR URL (the PR-tab detail passes its own); falls back to the report's. */
  prUrl?: string | null;
  placement?: "standalone" | "header";
}

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);
const HEADER_ACTION_CLASS = "h-7 gap-1.5 px-2.5 text-[12px]";

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
  const reportsForBulk = useMemo(() => [report], [report]);
  const bulkActions = useInboxBulkActions(
    reportsForBulk,
    report.id,
    "detail_pane",
  );
  const canDefer =
    report.status === "ready" ||
    report.status === "failed" ||
    report.status === "pending_input";

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
        {canDefer && (
          <DropdownMenuItem
            disabled={
              bulkActions.snoozeDisabledReason !== null ||
              bulkActions.isSnoozing
            }
            onClick={() => void bulkActions.snoozeSelected()}
          >
            <ClockIcon size={13} />
            Defer
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
  const githubButton = safePrUrl ? (
    placement === "header" ? (
      <Button
        type="button"
        variant="outline"
        size="xs"
        className={HEADER_ACTION_CLASS}
        onClick={() => openExternalUrl(safePrUrl)}
      >
        <ArrowSquareOutIcon size={14} />
        Open PR in GitHub
      </Button>
    ) : (
      <Button
        type="button"
        variant="outline"
        size="xs"
        className={HEADER_ACTION_CLASS}
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
        {githubButton}
        <ReportChatToggle report={report} />
        {canDefer && (
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  type="button"
                  variant="outline"
                  size="icon-xs"
                  className="h-7 w-7"
                  aria-label="Defer"
                  loading={bulkActions.isSnoozing}
                  disabled={bulkActions.snoozeDisabledReason !== null}
                  onClick={() => void bulkActions.snoozeSelected()}
                />
              }
            >
              <ClockIcon size={13} />
            </TooltipTrigger>
            <TooltipContent>
              {bulkActions.snoozeDisabledReason ?? "Defer"}
            </TooltipContent>
          </Tooltip>
        )}
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="outline"
                size="icon-xs"
                className="h-7 w-7"
                aria-label="Copy link"
                onClick={() => copyInboxReportLink(report)}
              />
            }
          >
            <CopyIcon size={13} />
          </TooltipTrigger>
          <TooltipContent>Copy link</TooltipContent>
        </Tooltip>
        {refund.canRefund && (
          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger
                render={
                  <DropdownMenuTrigger
                    render={
                      <Button
                        type="button"
                        variant="outline"
                        size="icon-xs"
                        aria-label="More report actions"
                      >
                        <DotsThreeIcon size={13} weight="bold" />
                      </Button>
                    }
                  />
                }
              />
              <TooltipContent>More report actions</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" side="bottom" sideOffset={6}>
              <DropdownMenuItem
                disabled={refund.disabledReason !== null}
                onClick={() => setRefundOpen(true)}
              >
                <ReceiptIcon size={13} />
                Refund…
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
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
                size="xs"
                disabled={isCreatingCanvas || awaitingChannel}
                className={HEADER_ACTION_CLASS}
                title="Have the agent build a canvas from this report"
              >
                {isCreatingCanvas ? <Spinner /> : <ShapesIcon size={16} />}
                Visualize on a canvas
              </Button>
            }
          />
          <PopoverContent
            align="end"
            side="bottom"
            sideOffset={6}
            className="flex w-[420px] flex-col gap-2 p-3"
          >
            <span className="text-[13px] text-gray-11">
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
              <span className="text-[12px] text-gray-10">
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
