import { CaretDown, CaretRight, Robot } from "@phosphor-icons/react";
import { useChatMessageScroller } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import {
  collectSessionSubagents,
  findItemRow,
  type SessionSubagent,
} from "@posthog/ui/features/sessions/components/chat-thread/sessionSubagents";
import type { TurnRow } from "@posthog/ui/features/sessions/components/chat-thread/threadVirtualization";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import { StepIcon } from "@posthog/ui/primitives/StepList";
import { track } from "@posthog/ui/shell/analytics";
import { useMemo, useState } from "react";

function subagentDetail(subagent: SessionSubagent): string | undefined {
  switch (subagent.status) {
    case "in_progress":
      return subagent.currentTool ?? "Starting…";
    case "pending":
      return "Stopped";
    default:
      return subagent.result;
  }
}

function SubagentEntry({
  subagent,
  onJump,
}: {
  subagent: SessionSubagent;
  onJump: (subagent: SessionSubagent) => void;
}) {
  const detail = subagentDetail(subagent);
  return (
    <button
      type="button"
      onClick={() => onJump(subagent)}
      title="Show in thread"
      className="flex w-full cursor-pointer items-start gap-2 rounded-sm border-none bg-transparent px-2 py-1 text-left hover:bg-fill-hover"
    >
      <span className="flex h-5 w-5 shrink-0 items-center justify-center">
        <StepIcon status={subagent.status} />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-foreground text-xs">
          {subagent.label}
        </span>
        {detail && (
          <span
            className="truncate text-muted-foreground text-xs"
            title={detail}
          >
            {detail}
          </span>
        )}
      </span>
    </button>
  );
}

/**
 * Session-level list of every subagent the agent spawned, pinned under the thread. Collapsed it
 * shows the counts and what a running subagent does now. Expanded it lists each subagent with its
 * status and current tool or final result, and a click scrolls the thread to the subagent's row.
 *
 * Rendered in the thread's nav layer, under the scroller provider, so it can use the same jump as
 * the message picker. `jumpToMessage` is the windowed body's jump; without it the plain body's
 * engine jump is used.
 */
export function SubagentStatusBar({
  items,
  rows,
  jumpToMessage,
  onJumped,
  onBeforeJump,
}: {
  items: ConversationItem[];
  rows: TurnRow[];
  jumpToMessage?: (id: string) => boolean;
  onJumped?: (rowId: string) => void;
  onBeforeJump?: () => void;
}) {
  const { scrollToMessage } = useChatMessageScroller();
  const [expanded, setExpanded] = useState(false);
  const subagents = useMemo(() => collectSessionSubagents(items), [items]);

  if (subagents.length === 0) return null;

  const running = subagents.filter((s) => s.status === "in_progress");
  const failedCount = subagents.filter((s) => s.status === "failed").length;
  const live = running.at(-1);

  const handleToggle = () => {
    if (!expanded) {
      track(ANALYTICS_EVENTS.SUBAGENT_PANEL_OPENED, {
        subagent_count: subagents.length,
        running_count: running.length,
      });
    }
    setExpanded(!expanded);
  };

  const handleJump = (subagent: SessionSubagent) => {
    const target = findItemRow(rows, subagent.itemId);
    if (!target) return;
    track(ANALYTICS_EVENTS.SUBAGENT_PANEL_JUMPED, { status: subagent.status });
    onBeforeJump?.();
    const rowId = jumpToMessage ? target.rowId : target.turnId;
    (jumpToMessage ?? scrollToMessage)(rowId);
    onJumped?.(rowId);
  };

  const counts = [
    `${subagents.length} ${subagents.length === 1 ? "subagent" : "subagents"}`,
    running.length > 0 ? `${running.length} running` : null,
    failedCount > 0 ? `${failedCount} failed` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="border-border border-t bg-muted">
      <div className="mx-auto" style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}>
        <button
          type="button"
          onClick={handleToggle}
          aria-expanded={expanded}
          className="flex w-full cursor-pointer items-center gap-2 border-none bg-transparent px-3 py-2 text-left"
        >
          {expanded ? (
            <CaretDown size={12} className="shrink-0 text-muted-foreground" />
          ) : (
            <CaretRight size={12} className="shrink-0 text-muted-foreground" />
          )}
          <Robot size={14} className="shrink-0 text-muted-foreground" />
          <span className="whitespace-nowrap text-foreground text-xs">
            {counts}
          </span>
          {live && (
            <span className="min-w-0 truncate text-muted-foreground text-xs">
              {live.currentTool
                ? `${live.label}: ${live.currentTool}`
                : live.label}
            </span>
          )}
        </button>

        {expanded && (
          <div className="max-h-[40vh] overflow-y-auto border-border border-t px-1 py-1">
            {subagents.map((subagent) => (
              <SubagentEntry
                key={subagent.key}
                subagent={subagent}
                onJump={handleJump}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
