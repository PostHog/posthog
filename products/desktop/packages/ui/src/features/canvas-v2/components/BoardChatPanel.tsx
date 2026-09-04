import {
  ArrowUpIcon,
  ChatCircleIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react";
import {
  Button,
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from "@posthog/quill";
import type { CanvasV2Snapshot } from "@posthog/shared";
import { BoardPanel } from "@posthog/ui/features/canvas-v2/components/BoardPanel";
import { useStartBoardSession } from "@posthog/ui/features/canvas-v2/hooks/useStartBoardSession";
import { EmbeddedSessionView } from "@posthog/ui/features/sessions/components/EmbeddedSessionView";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  CHAT_COMPOSER_PLACEHOLDER,
  CHAT_EXAMPLES,
  CHAT_NEW_SESSION_ACTION,
  CHAT_PANEL_CLOSE,
  CHAT_PANEL_TITLE,
  CHAT_PLACEHOLDER,
  CHAT_START_ACTION,
  CHAT_STARTER_TITLE,
} from "../canvasV2Copy";
import { setTaskForBoard } from "../hooks/useBoardViewportStore";

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
    <BoardPanel
      title={CHAT_PANEL_TITLE}
      closeLabel={CHAT_PANEL_CLOSE}
      onClose={onClose}
      actions={
        taskId ? (
          <Button
            variant="link-muted"
            size="sm"
            onClick={() => setTaskForBoard(boardId, undefined)}
          >
            {CHAT_NEW_SESSION_ACTION}
          </Button>
        ) : null
      }
    >
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
    </BoardPanel>
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
  const [prompt, setPrompt] = useState("");
  const { start, pending } = useStartBoardSession({
    boardId,
    boardName,
    snapshot,
    headSeq,
  });

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-4 px-4 text-center">
        <span className="flex size-10 items-center justify-center rounded-full bg-(--accent-a3) text-(--accent-11)">
          <ChatCircleIcon size={19} />
        </span>
        <div className="flex flex-col gap-1">
          <p className="font-semibold text-[13px]">{CHAT_STARTER_TITLE}</p>
          <p className="text-(--gray-11) text-[12px] leading-relaxed">
            {CHAT_PLACEHOLDER}
          </p>
        </div>
        <div className="flex w-full flex-col gap-1.5">
          {CHAT_EXAMPLES.map((example) => (
            <button
              key={example}
              type="button"
              className="rounded-(--radius-2) border border-(--gray-4) px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-(--gray-3)"
              onClick={() => setPrompt(example)}
            >
              {example}
            </button>
          ))}
        </div>
      </div>
      <div className="shrink-0 border-(--gray-4) border-t p-3">
        <InputGroup>
          <InputGroupTextarea
            value={prompt}
            placeholder={CHAT_COMPOSER_PLACEHOLDER}
            className="min-h-[52px] resize-none text-[13px]"
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                void start(prompt);
              }
            }}
          />
          <InputGroupAddon align="block-end">
            <InputGroupButton
              className="ml-auto"
              size="icon-sm"
              variant="primary"
              aria-label={CHAT_START_ACTION}
              disabled={pending || prompt.trim().length === 0}
              onClick={() => void start(prompt)}
            >
              {pending ? (
                <SpinnerGapIcon size={14} className="animate-spin" />
              ) : (
                <ArrowUpIcon size={14} />
              )}
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </div>
    </div>
  );
}
