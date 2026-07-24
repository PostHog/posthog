import {
  ChatCircleIcon,
  PencilSimpleIcon,
  SidebarSimpleIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { FreeformGenerateBar } from "@posthog/ui/features/canvas/freeform/FreeformGenerateBar";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { Flex, Text, Tooltip } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import type { Ref } from "react";

// The canvas's right-hand dock. While a generation/edit run is in flight it
// shows that run's live chat (steering/queue included); otherwise it shows the
// edit composer for the next change. Header carries a minimize control that
// collapses the panel to a thin rail (handled by the parent).
export function CanvasSidePanel({
  effectiveTaskId,
  onMinimize,
  dashboardId,
  channelId,
  channelName,
  name,
  templateId,
  currentCode,
  editorRef,
  onStarted,
}: {
  effectiveTaskId: string | null;
  onMinimize: () => void;
  dashboardId: string;
  channelId: string;
  channelName: string;
  name: string;
  templateId?: string;
  currentCode?: string;
  // Exposes the edit composer's editor so self-repair can prefill it.
  editorRef?: Ref<EditorHandle>;
  onStarted?: (taskId: string) => void;
}) {
  const isChat = !!effectiveTaskId;

  return (
    <Flex direction="column" className="h-full min-w-0 bg-gray-1">
      <Flex
        align="center"
        justify="between"
        className="h-10 shrink-0 items-center border-b bg-chrome px-3"
      >
        <Flex align="center" gap="2" className="min-w-0">
          {isChat ? (
            <ChatCircleIcon size={15} className="shrink-0 text-gray-10" />
          ) : (
            <PencilSimpleIcon size={15} className="shrink-0 text-gray-10" />
          )}
          <Text size="2" weight="medium" className="truncate text-gray-12">
            {isChat ? "Chat" : "Edit canvas"}
          </Text>
        </Flex>
        <Tooltip content="Minimize panel">
          <Button
            size="icon"
            variant="default"
            aria-label="Minimize panel"
            onClick={onMinimize}
          >
            <SidebarSimpleIcon size={16} />
          </Button>
        </Tooltip>
      </Flex>

      <div className="min-h-0 flex-1">
        {effectiveTaskId ? (
          <CanvasChatLoader taskId={effectiveTaskId} />
        ) : (
          <Flex direction="column" className="h-full p-3">
            <FreeformGenerateBar
              ref={editorRef}
              sessionId={`canvas:${dashboardId}`}
              dashboardId={dashboardId}
              channelId={channelId}
              channelName={channelName}
              name={name}
              templateId={templateId}
              currentCode={currentCode}
              onStarted={onStarted}
            />
          </Flex>
        )}
      </div>
    </Flex>
  );
}

// Resolves the run's task (shared react-query cache, so this dedupes with the
// canvas view's own poll) and renders its live chat once available.
function CanvasChatLoader({ taskId }: { taskId: string }) {
  const { data: task } = useQuery(taskDetailQuery(taskId));

  if (!task) {
    return (
      <Flex align="center" justify="center" className="h-full">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </Flex>
    );
  }

  return <EmbeddedSessionView task={task} />;
}
