import { PencilSimple } from "@phosphor-icons/react";
import { Text } from "@radix-ui/themes";
import { CodePreview } from "./CodePreview";
import { FileMentionChip } from "./FileMentionChip";
import { ToolRow } from "./ToolRow";
import {
  findDiffContent,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

function getDiffStats(
  oldText: string | null | undefined,
  newText: string | null | undefined,
): { added: number; removed: number } {
  const oldLines = oldText ? oldText.split("\n") : [];
  const newLines = newText ? newText.split("\n") : [];

  if (!oldText) {
    return { added: newLines.length, removed: 0 };
  }

  const oldCounts = new Map<string, number>();
  for (const line of oldLines) {
    oldCounts.set(line, (oldCounts.get(line) ?? 0) + 1);
  }

  const newCounts = new Map<string, number>();
  for (const line of newLines) {
    newCounts.set(line, (newCounts.get(line) ?? 0) + 1);
  }

  let added = 0;
  let removed = 0;

  for (const [line, count] of newCounts) {
    const oldCount = oldCounts.get(line) ?? 0;
    if (count > oldCount) added += count - oldCount;
  }

  for (const [line, count] of oldCounts) {
    const newCount = newCounts.get(line) ?? 0;
    if (count > newCount) removed += count - newCount;
  }

  return { added, removed };
}

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

  return (
    <ToolRow
      icon={PencilSimple}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen={!isPlanFile}
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
        <Text className="font-mono text-[13px]">
          <span className="text-green-11">+{diffStats.added}</span>{" "}
          <span className="text-red-11">-{diffStats.removed}</span>
        </Text>
      )}
    </ToolRow>
  );
}
