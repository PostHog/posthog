import { FolderSimple } from "@phosphor-icons/react";
import { FileMentionChip } from "./FileMentionChip";
import { ToolRow } from "./ToolRow";
import type { ToolViewProps } from "./toolCallUtils";
import {
  ContentPre,
  getContentText,
  stripCodeFences,
  ToolTitle,
  useToolCallStatus,
} from "./toolCallUtils";

export function ListToolView({
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
  const path = locations?.[0]?.path;
  const output = stripCodeFences(getContentText(content) ?? "");
  const body = output ? <ContentPre>{output}</ContentPre> : undefined;

  return (
    <ToolRow
      icon={FolderSimple}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      content={body}
    >
      <ToolTitle className="shrink-0 whitespace-nowrap">
        List files in
      </ToolTitle>
      {path && <FileMentionChip filePath={path} />}
    </ToolRow>
  );
}
