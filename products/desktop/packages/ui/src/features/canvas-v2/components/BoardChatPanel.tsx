import { SpinnerGapIcon } from "@phosphor-icons/react";
import { buildBoardSessionPrompt } from "@posthog/core/canvas-v2/boardPrompt";
import { linkTaskToBoard } from "@posthog/core/canvas-v2/boardTaskLinks";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { Button, Text, Textarea } from "@posthog/quill";
import type { CanvasV2Snapshot } from "@posthog/shared";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  CHAT_NEW_SESSION_ACTION,
  CHAT_PANEL_CLOSE,
  CHAT_PANEL_TITLE,
  CHAT_PLACEHOLDER,
  CHAT_START_ACTION,
  CHAT_START_ERROR,
} from "../canvasV2Copy";
import { setTaskForBoard } from "../hooks/useBoardViewportStore";
import { CANVAS_V2_LIBRARY } from "../library/registry";

export interface BoardChatPanelProps {
  boardId: string;
  boardName: string;
  snapshot: CanvasV2Snapshot;
  headSeq: number;
  taskId: string | undefined;
  onClose: () => void;
}

/** The agent session of one person on this board. */
export function BoardChatPanel({
  boardId,
  boardName,
  snapshot,
  headSeq,
  taskId,
  onClose,
}: BoardChatPanelProps) {
  return (
    <div className="@container flex h-full min-h-0 w-full flex-col overflow-x-hidden border-l">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
        <Text weight="medium">{CHAT_PANEL_TITLE}</Text>
        <div className="flex items-center gap-1">
          {taskId ? (
            <Button
              variant="link-muted"
              size="sm"
              onClick={() => setTaskForBoard(boardId, undefined)}
            >
              {CHAT_NEW_SESSION_ACTION}
            </Button>
          ) : null}
          <Button variant="link-muted" size="sm" onClick={onClose}>
            {CHAT_PANEL_CLOSE}
          </Button>
        </div>
      </div>
      {taskId ? (
        <BoardChatSession taskId={taskId} />
      ) : (
        <BoardChatStarter
          boardId={boardId}
          boardName={boardName}
          snapshot={snapshot}
          headSeq={headSeq}
        />
      )}
    </div>
  );
}

function BoardChatSession({ taskId }: { taskId: string }) {
  const { data: task } = useQuery(taskDetailQuery(taskId));

  if (!task) {
    return (
      <div className="flex h-full items-center justify-center">
        <SpinnerGapIcon size={18} className="animate-spin text-gray-9" />
      </div>
    );
  }

  return (
    <div className="min-h-0 flex-1">
      <EmbeddedSessionView task={task} />
    </div>
  );
}

function BoardChatStarter({
  boardId,
  boardName,
  snapshot,
  headSeq,
}: {
  boardId: string;
  boardName: string;
  snapshot: CanvasV2Snapshot;
  headSeq: number;
}) {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const [prompt, setPrompt] = useState("");
  const [pending, setPending] = useState(false);

  const start = async (): Promise<void> => {
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
          workspaceMode: "local",
          allowNoRepo: true,
          runtime: "acp",
          adapter: "claude",
          executionMode: "bypassPermissions",
        },
        (output) => {
          linkTaskToBoard(output.task.id, boardId);
          setTaskForBoard(boardId, output.task.id);
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
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
      <Textarea
        value={prompt}
        onChange={(event) => setPrompt(event.target.value)}
        placeholder={CHAT_PLACEHOLDER}
        className="min-h-24 flex-1"
      />
      <Button
        onClick={() => void start()}
        disabled={pending || prompt.trim().length === 0}
        loading={pending}
      >
        {CHAT_START_ACTION}
      </Button>
    </div>
  );
}
