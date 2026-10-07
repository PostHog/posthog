import { Plugs } from "@phosphor-icons/react";
import {
  getPostHogExecDisplay,
  isPostHogExecTool,
} from "@posthog/core/sessions/posthogExecDisplay";
import { readMcpToolDescriptor } from "@posthog/shared";
import { ToolRow } from "../../sessions/components/session-update/ToolRow";
import {
  compactInput,
  ToolTitle,
  type ToolViewProps,
  toolCallDetails,
  truncateText,
  useToolCallStatus,
} from "../../sessions/components/session-update/toolCallUtils";
import { parseMcpToolKey } from "../utils/mcp-app-host-utils";

const POSTHOG_EXEC_INPUT_PREVIEW_MAX_LENGTH = 60;

interface McpToolViewProps extends ToolViewProps {
  mcpToolName: string;
}

export function McpToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  mcpToolName,
  expanded = false,
}: McpToolViewProps) {
  const { status, rawInput, content } = toolCall;
  const { isLoading, isFailed, wasCancelled, isComplete } = useToolCallStatus(
    status,
    turnCancelled,
    turnComplete,
  );
  const { serverName: defaultServerName, toolName: defaultToolName } =
    parseMcpToolKey(mcpToolName);
  const descriptor = readMcpToolDescriptor(toolCall._meta);
  const posthogDisplay = isPostHogExecTool(mcpToolName)
    ? getPostHogExecDisplay(rawInput)
    : null;
  const toolName =
    posthogDisplay?.label ?? descriptor?.title ?? defaultToolName;
  const displayName = `${defaultServerName} - ${toolName}`;
  const inputPreview = posthogDisplay
    ? posthogDisplay.input
      ? truncateText(
          posthogDisplay.input,
          POSTHOG_EXEC_INPUT_PREVIEW_MAX_LENGTH,
        )
      : undefined
    : compactInput(rawInput);

  return (
    <ToolRow
      icon={Plugs}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen={expanded}
      content={toolCallDetails({ rawInput, content, isComplete, isFailed })}
    >
      <ToolTitle>{displayName}</ToolTitle>
      {inputPreview && (
        <ToolTitle>
          <span className="text-muted-foreground/50">{inputPreview}</span>
        </ToolTitle>
      )}
    </ToolRow>
  );
}
