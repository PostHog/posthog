import { buildBoardSessionPrompt } from "@posthog/core/canvas-v2/boardPrompt";
import { linkTaskToBoard } from "@posthog/core/canvas-v2/boardTaskLinks";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import type { CanvasV2Snapshot } from "@posthog/shared";
import { CANVAS_TASK_ORIGIN } from "@posthog/shared";
import { CHAT_START_ERROR } from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { setTaskForBoard } from "@posthog/ui/features/canvas-v2/hooks/useBoardViewportStore";
import { CANVAS_V2_LIBRARY } from "@posthog/ui/features/canvas-v2/library/registry";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useCallback, useState } from "react";

export interface StartBoardSessionArgs {
  boardId: string;
  boardName: string;
  snapshot: CanvasV2Snapshot;
  headSeq: number;
  onStarted?: (taskId: string) => void;
}

export interface StartBoardSession {
  start: (prompt: string) => Promise<void>;
  pending: boolean;
}

export function useStartBoardSession({
  boardId,
  boardName,
  snapshot,
  headSeq,
  onStarted,
}: StartBoardSessionArgs): StartBoardSession {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const [pending, setPending] = useState(false);

  const start = useCallback(
    async (prompt: string): Promise<void> => {
      const text = prompt.trim();
      if (text.length === 0 || pending) return;
      setPending(true);
      try {
        const result = await taskService.createTask(
          {
            content: buildBoardSessionPrompt({
              boardName,
              snapshot,
              headSeq,
              userPrompt: text,
              library: CANVAS_V2_LIBRARY.map((entry) => ({
                name: entry.name,
                label: entry.label,
                description: entry.description,
                code: entry.code,
              })),
            }),
            taskDescription: `Canvas: ${boardName}`,
            originProduct: CANVAS_TASK_ORIGIN,
            workspaceMode: "local",
            allowNoRepo: true,
            runtime: "acp",
            adapter: "claude",
            executionMode: "bypassPermissions",
          },
          (output) => {
            linkTaskToBoard(output.task.id, boardId);
            setTaskForBoard(boardId, output.task.id);
            onStarted?.(output.task.id);
          },
        );
        if (!result.success) {
          toastError(CHAT_START_ERROR, result.error);
        }
      } catch (error) {
        toastError(CHAT_START_ERROR, error);
      } finally {
        setPending(false);
      }
    },
    [boardId, boardName, headSeq, onStarted, pending, snapshot, taskService],
  );

  return { start, pending };
}
