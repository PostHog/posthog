import { useServiceOptional } from "@posthog/di/react";
import { readAgentToolName, readMcpToolName } from "@posthog/shared";
import { DeleteToolView } from "@posthog/ui/features/sessions/components/session-update/DeleteToolView";
import { EditToolView } from "@posthog/ui/features/sessions/components/session-update/EditToolView";
import { ExecuteToolView } from "@posthog/ui/features/sessions/components/session-update/ExecuteToolView";
import { FetchToolView } from "@posthog/ui/features/sessions/components/session-update/FetchToolView";
import { MoveToolView } from "@posthog/ui/features/sessions/components/session-update/MoveToolView";
import { PlanApprovalView } from "@posthog/ui/features/sessions/components/session-update/PlanApprovalView";
import { QuestionToolView } from "@posthog/ui/features/sessions/components/session-update/QuestionToolView";
import { ReadToolView } from "@posthog/ui/features/sessions/components/session-update/ReadToolView";
import { SearchToolView } from "@posthog/ui/features/sessions/components/session-update/SearchToolView";
import { ThinkToolView } from "@posthog/ui/features/sessions/components/session-update/ThinkToolView";
import { ToolCallView } from "@posthog/ui/features/sessions/components/session-update/ToolCallView";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Box } from "@radix-ui/themes";
import type { ConversationItem, TurnContext } from "../buildConversationItems";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { isSubagentSpawnTool } from "./collaborationTools";
import {
  MCP_TOOL_BLOCK_COMPONENT,
  type McpToolBlockComponent,
} from "./identifiers";
import { SubagentToolView } from "./SubagentToolView";

interface ToolCallBlockProps extends ToolViewProps {
  childItems?: ConversationItem[];
  childItemsMap?: Map<string, ConversationItem[]>;
}

export function ToolCallBlock({
  toolCall,
  turnCancelled,
  turnComplete,
  childItems,
  childItemsMap,
}: ToolCallBlockProps) {
  const McpToolBlock = useServiceOptional<McpToolBlockComponent>(
    MCP_TOOL_BLOCK_COMPONENT,
  );
  const toolName = readAgentToolName(toolCall._meta);
  const mcpToolName = readMcpToolName(toolCall._meta);
  const chatChrome = useChatThreadChrome();

  if (toolName === "EnterPlanMode") {
    return null;
  }

  const props = { toolCall, turnCancelled, turnComplete };

  if (isSubagentSpawnTool(toolName)) {
    const subagentChildItems = childItems ?? [];
    const turnContext: TurnContext = {
      toolCalls: buildChildToolCallsMap(subagentChildItems),
      childItems: childItemsMap ?? new Map(),
      turnCancelled: turnCancelled ?? false,
      turnComplete: turnComplete ?? false,
    };
    return (
      <Box>
        <SubagentToolView
          {...props}
          childItems={subagentChildItems}
          turnContext={turnContext}
        />
      </Box>
    );
  }

  if (mcpToolName) {
    return (
      <Box className={chatChrome ? "" : "pl-3"}>
        {McpToolBlock ? (
          <McpToolBlock {...props} mcpToolName={mcpToolName} />
        ) : (
          <ToolCallView {...props} agentToolName={mcpToolName} />
        )}
      </Box>
    );
  }

  const content = (() => {
    switch (toolCall.kind) {
      case "switch_mode":
        return <PlanApprovalView {...props} />;
      case "execute":
        return <ExecuteToolView {...props} />;
      case "read":
        return <ReadToolView {...props} />;
      case "edit":
        return <EditToolView {...props} />;
      case "delete":
        return <DeleteToolView {...props} />;
      case "move":
        return <MoveToolView {...props} />;
      case "search":
        return <SearchToolView {...props} />;
      case "think":
        return <ThinkToolView {...props} />;
      case "fetch":
        return <FetchToolView {...props} />;
      case "question":
        return <QuestionToolView {...props} />;
      default:
        return <ToolCallView {...props} agentToolName={toolName} />;
    }
  })();

  return <Box>{content}</Box>;
}

function buildChildToolCallsMap(
  childItems: ConversationItem[],
): Map<string, ToolCall> {
  const map = new Map<string, ToolCall>();
  for (const item of childItems) {
    if (
      item.type === "session_update" &&
      item.update.sessionUpdate === "tool_call"
    ) {
      const tc = item.update as unknown as ToolCall;
      if (tc.toolCallId) {
        map.set(tc.toolCallId, tc);
      }
    }
  }
  return map;
}
