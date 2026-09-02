import { MagnifyingGlass } from "@phosphor-icons/react";
import { ToolRow } from "./ToolRow";
import {
  ContentPre,
  getContentText,
  ToolTitle,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

export function SearchToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, content, title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const searchResults = getContentText(content) ?? "";
  const hasResults = searchResults.trim().length > 0;
  const resultCount = hasResults
    ? searchResults.split("\n").filter((line) => line.trim().length > 0).length
    : 0;

  return (
    <ToolRow
      icon={MagnifyingGlass}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      content={
        hasResults ? <ContentPre>{searchResults}</ContentPre> : undefined
      }
    >
      <ToolTitle className="min-w-0 shrink truncate">
        <span className="font-mono">{title || "Search"}</span>
      </ToolTitle>
      {hasResults && (
        <ToolTitle className="shrink-0 whitespace-nowrap">
          {resultCount} {resultCount === 1 ? "result" : "results"}
        </ToolTitle>
      )}
    </ToolRow>
  );
}
