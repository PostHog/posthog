import { PI_SESSION_CONTROLLER } from "@posthog/core/pi-runtime/identifiers";
import type {
  PiModelOption,
  PiQueueMode,
  PiSessionController,
  PiThinkingLevel,
} from "@posthog/core/pi-runtime/piSessionController";
import { useService } from "@posthog/di/react";
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@posthog/quill";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { ChatThread } from "@posthog/ui/features/sessions/components/chat-thread/ChatThread";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import { useMessagingMode } from "@posthog/ui/features/sessions/hooks/useMessagingMode";
import { useMessagingModeStore } from "@posthog/ui/features/sessions/messagingModeStore";
import { useWorkspace } from "@posthog/ui/features/workspace/useWorkspace";
import { toast } from "@posthog/ui/primitives/toast";
import { TaskDetailSkeleton } from "@posthog/ui/router/routeSkeletons";
import { Box, Flex } from "@radix-ui/themes";
import { useCallback, useEffect } from "react";
import { useStore } from "zustand";
import {
  PiMessagingModeSelector,
  PiModelSelector,
  PiThinkingLevelSelector,
} from "./PiSessionControls";

interface PiSessionViewProps {
  taskId: string;
}

export function PiSessionView({ taskId }: PiSessionViewProps) {
  const piSessionController = useService<PiSessionController>(
    PI_SESSION_CONTROLLER,
  );
  const session = useStore(
    piSessionController.store,
    (state) => state.sessions[taskId],
  );
  const draftActions = useDraftStore((state) => state.actions);
  const workspace = useWorkspace(taskId);
  const repoPath = workspace?.worktreePath ?? workspace?.folderPath;
  const messagingMode = useMessagingMode(taskId);
  const setMessagingMode = useMessagingModeStore((state) => state.setMode);

  useEffect(() => {
    void piSessionController.ensureConnected(taskId);
    return () => piSessionController.disconnect(taskId);
  }, [piSessionController, taskId]);

  const sessionAvailable = session?.connectionState === "connected";
  const status = session?.status;
  const isStreaming = status?.isStreaming ?? false;
  const isCompacting = status?.isCompacting ?? false;
  const isBashRunning = session?.isBashRunning ?? false;

  useEffect(() => {
    draftActions.setContext(taskId, {
      taskId,
      repoPath,
      disabled: !sessionAvailable || isCompacting,
      isLoading: isStreaming || isBashRunning,
    });
  }, [
    draftActions,
    isBashRunning,
    isCompacting,
    isStreaming,
    repoPath,
    sessionAvailable,
    taskId,
  ]);

  useEffect(() => {
    if (!session?.commands) {
      return;
    }

    const piCommands = session.commands
      .filter((command) => command.name !== "compact")
      .map((command) => ({
        name: command.name,
        description: command.description ?? "",
      }));

    draftActions.setCommands(taskId, [
      {
        name: "compact",
        description: "Compact the current Pi session context",
        input: { hint: "optional instructions" },
      },
      ...piCommands,
    ]);
  }, [draftActions, session?.commands, taskId]);

  const sendPrompt = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message) {
        return;
      }

      const action = piSessionController.getSubmitAction(
        message,
        isStreaming,
        messagingMode,
      );
      void piSessionController
        .submit(taskId, message, isStreaming, messagingMode)
        .then(() => {
          if (action === "compact") {
            toast.success("Pi context compacted");
          }
        })
        .catch(() => {
          const failureMessage =
            action === "compact"
              ? "Failed to compact Pi context"
              : "Failed to send message to Pi";
          toast.error(failureMessage);
        });
    },
    [isStreaming, messagingMode, piSessionController, taskId],
  );

  const setModel = useCallback(
    (model: PiModelOption) => {
      void piSessionController
        .setModel(taskId, model)
        .catch(() => toast.error("Failed to change Pi model"));
    },
    [piSessionController, taskId],
  );

  const setThinkingLevel = useCallback(
    (level: PiThinkingLevel) => {
      void piSessionController
        .setThinkingLevel(taskId, level)
        .catch(() => toast.error("Failed to change Pi thinking level"));
    },
    [piSessionController, taskId],
  );

  const setQueueMode = useCallback(
    (mode: PiQueueMode) => {
      void piSessionController
        .setQueueMode(taskId, messagingMode, mode)
        .catch(() => toast.error("Failed to change Pi queue behavior"));
    },
    [messagingMode, piSessionController, taskId],
  );

  const toggleMessagingMode = useCallback(() => {
    const nextMode = messagingMode === "steer" ? "queue" : "steer";
    setMessagingMode(taskId, nextMode);
  }, [messagingMode, setMessagingMode, taskId]);

  const runBashCommand = (command: string) => {
    void piSessionController
      .bash(taskId, command)
      .catch(() => toast.error("Failed to run Pi bash command"));
  };

  const cancelPrompt = () => {
    if (isBashRunning) {
      void piSessionController.abortBash(taskId);
      return;
    }

    void piSessionController.abort(taskId);
  };

  const sessionError = session?.error;
  if (sessionError) {
    return (
      <Empty className="h-full">
        <EmptyHeader>
          <EmptyTitle>Pi session failed to start</EmptyTitle>
          <EmptyDescription>{sessionError}</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  if (!session || !status) {
    return <TaskDetailSkeleton />;
  }

  const pending = isStreaming || isBashRunning;
  const currentModel = session.models.find(
    (model) =>
      model.provider === status.model?.provider && model.id === status.model.id,
  );
  const thinkingLevels = currentModel?.thinkingLevels ?? [];
  const supportsThinking = thinkingLevels.some((level) => level !== "off");
  const queueMode =
    messagingMode === "steer" ? status.steeringMode : status.followUpMode;

  return (
    <Flex direction="column" height="100%">
      <Box className="min-h-0 flex-1">
        <ChatThread
          events={session.events}
          isPromptPending={pending}
          taskId={taskId}
          repoPath={repoPath}
        />
      </Box>
      <Box
        className="mx-auto w-full px-2 pb-3"
        style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}
      >
        <PromptInput
          sessionId={taskId}
          taskId={taskId}
          repoPath={repoPath}
          placeholder="Type a message..."
          disabled={!sessionAvailable || isCompacting}
          isLoading={pending}
          enableBashMode
          enableCommands
          modelSelector={
            <PiModelSelector
              models={session.models}
              currentModel={status.model}
              disabled={pending || isCompacting}
              onChange={setModel}
            />
          }
          reasoningSelector={
            supportsThinking ? (
              <PiThinkingLevelSelector
                level={status.thinkingLevel}
                levels={thinkingLevels}
                disabled={pending || isCompacting}
                onChange={setThinkingLevel}
              />
            ) : null
          }
          messagingModeToggle={
            <PiMessagingModeSelector
              mode={messagingMode}
              queueMode={queueMode}
              queuedCount={status.pendingMessageCount}
              disabled={isBashRunning}
              onModeChange={(mode) => setMessagingMode(taskId, mode)}
              onQueueModeChange={setQueueMode}
            />
          }
          onToggleMessagingMode={toggleMessagingMode}
          onSubmit={sendPrompt}
          onBashCommand={runBashCommand}
          onCancel={cancelPrompt}
        />
      </Box>
    </Flex>
  );
}
