import { Trash } from "@phosphor-icons/react";
import { Text } from "@radix-ui/themes";
import { FileMentionChip } from "./FileMentionChip";
import { ToolRow } from "./ToolRow";
import {
  type DiffContent,
  findDiffContent,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

function getDeletedLineCount(diff: DiffContent | undefined): number | null {
  if (!diff?.oldText) return null;
  return diff.oldText.split("\n").length;
}

export function DeleteToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, locations, content } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const filePath = locations?.[0]?.path ?? "";
  const diff = findDiffContent(content);
  const deletedLines = getDeletedLineCount(diff);

  return (
    <ToolRow
      icon={Trash}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
    >
      {filePath && <FileMentionChip filePath={filePath} />}
      {deletedLines !== null && (
        <Text className="font-mono text-[13px]">
          <span className="text-red-11">-{deletedLines}</span>
        </Text>
      )}
    </ToolRow>
  );
}
