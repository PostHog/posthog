import { FileText } from "@phosphor-icons/react";
import { SafeImagePreview } from "@posthog/ui/primitives/SafeImagePreview";
import { CodePreview } from "./CodePreview";
import { FileMentionChip } from "./FileMentionChip";
import { ToolRow } from "./ToolRow";
import {
  getContentImage,
  getReadToolContent,
  ToolTitle,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

export function ReadToolView({
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
  const startLine = locations?.[0]?.line ?? 0;
  const imageContent = getContentImage(content);
  const fileContent = imageContent ? undefined : getReadToolContent(content);
  const lineCount = fileContent ? fileContent.split("\n").length : null;
  const firstLineNumber = startLine + 1;

  const body = imageContent ? (
    <div className="bg-(--gray-2) p-2">
      <SafeImagePreview
        base64={imageContent.base64}
        mimeType={imageContent.mimeType}
        alt={filePath || "Read tool image preview"}
        className="max-h-96 max-w-full object-contain"
      />
    </div>
  ) : fileContent ? (
    <CodePreview
      content={fileContent}
      filePath={filePath}
      firstLineNumber={firstLineNumber}
    />
  ) : undefined;

  return (
    <ToolRow
      icon={FileText}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      content={body}
    >
      <ToolTitle className="shrink-0 whitespace-nowrap">
        {imageContent
          ? "Read image in"
          : `Read${lineCount !== null ? ` ${lineCount} lines in` : ""}`}
      </ToolTitle>
      {filePath && <FileMentionChip filePath={filePath} />}
    </ToolRow>
  );
}
