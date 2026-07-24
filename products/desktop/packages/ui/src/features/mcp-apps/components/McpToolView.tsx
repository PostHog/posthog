import { Plugs } from "@phosphor-icons/react";
import {
  getPostHogExecDisplay,
  isPostHogExecTool,
} from "../../posthog-mcp/utils/posthog-exec-display";
import { useChatThreadChrome } from "../../sessions/components/chat-thread/chatThreadChrome";
import { ToolRow } from "../../sessions/components/session-update/ToolRow";
import {
  ContentPre,
  compactInput,
  formatInput,
  getContentText,
  stripCodeFences,
  ToolTitle,
  type ToolViewProps,
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
  // New thread restyles the MCP header/output; the legacy thread keeps its original colours + the
  // input/output divider so ConversationView is unchanged when the chat thread is toggled off.
  const chatChrome = useChatThreadChrome();

  const { serverName: defaultServerName, toolName: defaultToolName } =
    parseMcpToolKey(mcpToolName);
  const posthogDisplay = isPostHogExecTool(mcpToolName)
    ? getPostHogExecDisplay(rawInput)
    : null;
  const serverName = posthogDisplay ? "posthog" : defaultServerName;
  const toolName = posthogDisplay?.label ?? defaultToolName;
  const inputPreview = posthogDisplay
    ? posthogDisplay.input
      ? truncateText(
          posthogDisplay.input,
          POSTHOG_EXEC_INPUT_PREVIEW_MAX_LENGTH,
        )
      : undefined
    : compactInput(rawInput);
  const fullInput = formatInput(rawInput);

  const output = stripCodeFences(getContentText(content) ?? "");
  const hasOutput = output.trim().length > 0;
  // Surface output for failures too, otherwise a failed call shows "(Failed)"
  // with no reason — the error text lives in `content`.
  const showOutput = (isComplete || isFailed) && hasOutput;

  const body =
    fullInput || showOutput ? (
      <>
        {fullInput && <ContentPre>{fullInput}</ContentPre>}
        {showOutput &&
          (chatChrome ? (
            <ContentPre>{output}</ContentPre>
          ) : (
            <div className={fullInput ? "border-gray-6 border-t" : undefined}>
              <ContentPre>{output}</ContentPre>
            </div>
          ))}
      </>
    ) : undefined;

  const labelClass = chatChrome ? "text-muted-foreground" : "text-gray-10";
  const previewClass = chatChrome
    ? "text-muted-foreground/50"
    : "text-accent-11";

  return (
    <ToolRow
      icon={Plugs}
      isLoading={isLoading}
      isFailed={isFailed}
      wasCancelled={wasCancelled}
      defaultOpen={expanded}
      content={body}
    >
      <ToolTitle>
        <span className={labelClass}>{serverName}</span>
        {" - "}
        {toolName}
        <span className={labelClass}>{" (MCP)"}</span>
      </ToolTitle>
      {inputPreview && (
        <ToolTitle>
          <span className={previewClass}>{inputPreview}</span>
        </ToolTitle>
      )}
    </ToolRow>
  );
}
