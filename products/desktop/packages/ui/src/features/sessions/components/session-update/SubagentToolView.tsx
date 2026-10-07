import { Robot } from "@phosphor-icons/react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import {
  LoadingIcon,
  type ToolViewProps,
  useToolCallStatus,
} from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import type { ConversationItem, TurnContext } from "../buildConversationItems";
import { SessionUpdateView } from "./SessionUpdateView";
import { isShowActionsItem } from "./showActionsItem";
import { ToolRow } from "./ToolRow";

interface SubagentToolViewProps extends ToolViewProps {
  childItems: ConversationItem[];
  turnContext: TurnContext;
}

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

  const renderItems = (items: ConversationItem[]) =>
    items.map((child) =>
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
    );

  const nestedItems: ConversationItem[] = [];
  const actionItems: ConversationItem[] = [];
  for (const child of childItems) {
    (isShowActionsItem(child, turnContext.toolCalls)
      ? actionItems
      : nestedItems
    ).push(child);
  }
  const nestedContent =
    nestedItems.length > 0 ? renderItems(nestedItems) : undefined;
  const actionContent = renderItems(actionItems);

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
        content={nestedContent}
      >
        <span>
          <span className="font-medium text-gray-12">Subagent</span>
          {title && title !== "Subagent" ? ` · ${title}` : ""}
        </span>
      </ToolRow>
      {actionContent}
    </div>
  );
}
