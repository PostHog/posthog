import {
  ArrowsInSimple as ArrowsInSimpleIcon,
  ArrowsOutSimple as ArrowsOutSimpleIcon,
  Robot,
} from "@phosphor-icons/react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import {
  LoadingIcon,
  StatusIndicators,
  type ToolViewProps,
  useToolCallStatus,
} from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";
import { type ReactNode, useState } from "react";
import type { ConversationItem, TurnContext } from "../buildConversationItems";
import { useChatThreadChrome } from "../chat-thread/chatThreadChrome";
import { SessionUpdateView } from "./SessionUpdateView";
import { ToolRow } from "./ToolRow";

interface SubagentToolViewProps extends ToolViewProps {
  childItems: ConversationItem[];
  turnContext: TurnContext;
  defaultExpanded?: boolean;
  /** Replaces the "Subagent · title" header, for callers with their own name for the row. */
  header?: ReactNode;
  /** What the subagent says now, shown beside the title while it runs. */
  status?: ReactNode;
  /** Extra body content, below the child tool calls and hidden with them. */
  footer?: ReactNode;
}

/**
 * A subagent (Task/Agent) call. The new thread renders it as a single `ToolRow` (ChatMarker chrome)
 * whose collapsible body holds the subagent's own child tool calls. The legacy thread keeps its
 * bespoke bordered box + expand button so ConversationView is unchanged when the chat thread is off.
 */
export function SubagentToolView({
  toolCall,
  turnCancelled,
  turnComplete,
  childItems,
  turnContext,
  defaultExpanded = false,
  header,
  status,
  footer,
}: SubagentToolViewProps) {
  const { title } = toolCall;
  const { isLoading, isFailed, wasCancelled } = useToolCallStatus(
    toolCall.status,
    turnCancelled,
    turnComplete,
  );
  const chatChrome = useChatThreadChrome();
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

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
  const body =
    childContent || footer ? (
      <>
        {childContent}
        {footer}
      </>
    ) : undefined;

  // Legacy thread: bespoke bordered box with an expand toggle.
  if (!chatChrome) {
    return (
      <Box className="max-w-4xl overflow-hidden rounded-sm border border-gray-6 bg-gray-1">
        <button
          type="button"
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex w-full cursor-pointer items-center justify-between border-none bg-transparent px-3 py-2"
        >
          <Flex align="center" gap="2">
            <Tooltip>
              <TooltipTrigger
                render={
                  <span className="flex items-center">
                    <LoadingIcon
                      icon={Robot}
                      isLoading={isLoading}
                      className="text-gray-10"
                    />
                  </span>
                }
              />
              <TooltipContent side="top">
                Delegated to a subagent
              </TooltipContent>
            </Tooltip>
            {header ?? (
              <Text className="text-[13px] text-gray-10">
                <span className="font-medium text-gray-12">Subagent</span>
                {title && title !== "Subagent" ? ` · ${title}` : ""}
              </Text>
            )}
            <StatusIndicators isFailed={isFailed} wasCancelled={wasCancelled} />
          </Flex>
          {body && (
            <IconButton asChild size="1" variant="ghost" color="gray">
              <span>
                {isExpanded ? (
                  <ArrowsInSimpleIcon size={12} />
                ) : (
                  <ArrowsOutSimpleIcon size={12} />
                )}
              </span>
            </IconButton>
          )}
        </button>

        {isExpanded && body && (
          // [&_.tool-row-collapsible]:pl-1 so that inner ToolRow triggers have some more spacing on left
          <Box className="space-y-1 border-gray-6 border-t px-2 py-2 [&_.tool-row-collapsible]:pl-1">
            {body}
          </Box>
        )}
      </Box>
    );
  }

  // New thread: same minimal shape as ThoughtView — a single ToolRow whose collapsible body holds the
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
        defaultOpen={defaultExpanded}
        content={body}
        trailing={status}
      >
        {header ?? (
          <span>
            <span className="font-medium text-gray-12">Subagent</span>
            {title && title !== "Subagent" ? ` · ${title}` : ""}
          </span>
        )}
      </ToolRow>
    </div>
  );
}
