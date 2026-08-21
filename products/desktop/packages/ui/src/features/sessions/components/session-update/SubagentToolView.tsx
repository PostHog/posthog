import { Robot } from "@phosphor-icons/react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import {
  LoadingIcon,
  type ToolViewProps,
  useToolCallStatus,
} from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ConversationItem, TurnContext } from "../buildConversationItems";
import { SessionUpdateView } from "./SessionUpdateView";
import { ToolRow } from "./ToolRow";

interface SubagentToolViewProps extends ToolViewProps {
  childItems: ConversationItem[];
  turnContext: TurnContext;
}

/**
 * A subagent (Task/Agent) call: a single `ToolRow` whose collapsible body
 * holds the subagent's own child tool calls.
 */
export function SubagentToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  childItems,
  turnContext,
}: SubagentToolViewProps) {
  const { title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );

  const hasChildren = childItems.length > 0;
  const childContent = hasChildren
    ? childItems.map((child) =>
        child.type === "session_update" ? (
          <SessionUpdateView
            key={child.id}
            item={child.update}
            toolCalls={turnContext.toolCalls}
            childItems={turnContext.childItems}
            turnCancelled={turnContext.turnCancelled}
            turnComplete={turnContext.turnComplete}
          />
        ) : null,
      )
    : undefined;

  // Same minimal shape as ThoughtView — a single ToolRow whose collapsible body holds the
  // subagent's child tool calls. ToolRow supplies the ChatMarker chrome, so no bespoke box here.
  return (
    <div>
      <ToolRow
        leading={
          <Tooltip>
            <TooltipTrigger
              render={
                <span className="flex items-center">
                  <LoadingIcon icon={Robot} isLoading={isLoading} />
                </span>
              }
            />
            <TooltipContent side="top">Delegated to a subagent</TooltipContent>
          </Tooltip>
        }
        isLoading={isLoading}
        isFailed={isFailed}
        wasCancelled={wasCancelled}
        content={childContent}
      >
        <span>
          <span className="font-medium text-gray-12">Subagent</span>
          {title && title !== "Subagent" ? ` · ${title}` : ""}
        </span>
      </ToolRow>
    </div>
  );
}
