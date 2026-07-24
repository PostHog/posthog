import { ArrowsLeftRight } from "@phosphor-icons/react";
import { ToolRow } from "./ToolRow";
import {
  getFilename,
  ToolTitle,
  type ToolViewProps,
  useToolCallStatus,
} from "./toolCallUtils";

export function MoveToolView({
  toolCall,
  turnCancelled,
  turnComplete,
}: ToolViewProps) {
  const { status, locations, title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );

  const sourcePath = locations?.[0]?.path ?? "";
  const destPath = locations?.[1]?.path ?? "";

  return (
    <ToolRow
      icon={ArrowsLeftRight}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
    >
      <ToolTitle>
        {title ||
          (sourcePath && destPath ? (
            <>
              Move <span className="font-mono">{getFilename(sourcePath)}</span>{" "}
              → <span className="font-mono">{getFilename(destPath)}</span>
            </>
          ) : (
            "Move file"
          ))}
      </ToolTitle>
    </ToolRow>
  );
}
