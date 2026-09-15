import { PencilSimple } from "@phosphor-icons/react";
import { getDiffStats } from "@posthog/core/task-detail/cloudToolChanges";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { CodePreview } from "./CodePreview";
import { FileMentionChip } from "./FileMentionChip";
import { ToolRow } from "./ToolRow";
import {
  findDiffContent,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

export function EditToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, content, locations } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const diff = findDiffContent(content);
  const filePath = diff?.path ?? locations?.[0]?.path ?? "";
  const oldText = diff?.oldText;
  const newText = diff?.newText;
  const isNewFile = diff && !oldText;
  const hasDiff = diff && (oldText || newText);
  const diffStats = diff ? getDiffStats(oldText, newText) : null;

  const isPlanFile = filePath.includes("claude/plans/");
  const chatChrome = useChatThreadChrome();

  return (
    <ToolRow
      icon={PencilSimple}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      // Keep the legacy thread's inline diff behavior, but make tool details
      // opt-in in the experimental thread like every other tool result.
      defaultOpen={chatChrome ? false : !isPlanFile}
      content={
        hasDiff ? (
          <CodePreview
            content={newText ?? ""}
            filePath={filePath}
            oldContent={isNewFile ? null : oldText}
            maxHeight="700px"
            cacheKey={toolCall.toolCallId}
          />
        ) : undefined
      }
    >
      {filePath && <FileMentionChip filePath={filePath} />}
      {diffStats && (
        <span className="font-mono text-[13px]">
          <span className="text-green-11">+{diffStats.added ?? 0}</span>{" "}
          <span className="text-red-11">-{diffStats.removed ?? 0}</span>
        </span>
      )}
    </ToolRow>
  );
}
