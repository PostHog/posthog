import { ArrowRightIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { CanvasV2Snapshot } from "@posthog/shared";
import { BOARD_PROMPT_SUGGESTIONS } from "@posthog/ui/features/canvas-v2/boardPromptSuggestions";
import {
  BOARD_EMPTY_COMPOSER_PLACEHOLDER,
  BOARD_EMPTY_HINT,
  BOARD_EMPTY_LIBRARY_ACTION,
  BOARD_EMPTY_LIBRARY_TITLE,
  BOARD_EMPTY_SUGGESTIONS_TITLE,
  BOARD_EMPTY_TITLE,
} from "@posthog/ui/features/canvas-v2/canvasV2Copy";
import { useStartBoardSession } from "@posthog/ui/features/canvas-v2/hooks/useStartBoardSession";
import { libraryEntryIcon } from "@posthog/ui/features/canvas-v2/library/entryIcon";
import { libraryEntry } from "@posthog/ui/features/canvas-v2/library/registry";
import { PromptInput } from "@posthog/ui/features/message-editor/components/PromptInput";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { SuggestedPromptCard } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";
import { useRef } from "react";

const LIBRARY_STARTERS = ["kpi", "trend-chart", "sql-table", "sticky"];

export interface BoardEmptyHeroProps {
  boardId: string;
  boardName: string;
  snapshot: CanvasV2Snapshot;
  headSeq: number;
  onStarted: (taskId: string) => void;
  onAddFragment: (name: string) => void;
  onOpenLibrary: () => void;
}

export function BoardEmptyHero({
  boardId,
  boardName,
  snapshot,
  headSeq,
  onStarted,
  onAddFragment,
  onOpenLibrary,
}: BoardEmptyHeroProps) {
  const editorRef = useRef<EditorHandle>(null);
  const { start, pending } = useStartBoardSession({
    boardId,
    boardName,
    snapshot,
    headSeq,
    onStarted,
  });

  return (
    <div className="pointer-events-none absolute inset-0 flex items-center justify-center overflow-y-auto p-6">
      <div className="@container pointer-events-auto flex w-full max-w-[560px] flex-col gap-5">
        <div className="flex flex-col items-center gap-2 text-center">
          <span className="flex size-10 items-center justify-center rounded-xl bg-(--accent-a3) text-(--accent-11)">
            <SquaresFourIcon size={20} weight="duotone" />
          </span>
          <p className="font-semibold text-(--gray-12) text-[15px]">
            {BOARD_EMPTY_TITLE}
          </p>
          <p className="text-(--gray-11) text-[13px]">{BOARD_EMPTY_HINT}</p>
        </div>

        <div className="rounded-(--radius-4) border border-(--gray-4) border-solid bg-(--gray-1) shadow-lg">
          <PromptInput
            ref={editorRef}
            sessionId={`canvas-v2:${boardId}`}
            placeholder={BOARD_EMPTY_COMPOSER_PLACEHOLDER}
            editorHeight="large"
            disabled={pending}
            isLoading={pending}
            enableCommands
            enableBashMode={false}
            hideDefaultToolbar
            onSubmit={(text) => void start(text)}
          />
        </div>

        <div className="flex flex-col gap-2">
          <p className="px-1 font-medium text-(--gray-11) text-[12px]">
            {BOARD_EMPTY_SUGGESTIONS_TITLE}
          </p>
          <div className="grid @sm:grid-cols-2 grid-cols-1 gap-2">
            {BOARD_PROMPT_SUGGESTIONS.map((suggestion) => (
              <SuggestedPromptCard
                key={suggestion.label}
                suggestion={suggestion}
                onSelect={() => {
                  editorRef.current?.setContent(suggestion.prompt);
                  editorRef.current?.focus();
                }}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2 border-(--gray-4) border-t border-solid pt-4">
          <div className="flex items-center justify-between gap-2 px-1">
            <p className="font-medium text-(--gray-11) text-[12px]">
              {BOARD_EMPTY_LIBRARY_TITLE}
            </p>
            <Button
              variant="link-muted"
              size="sm"
              className="shrink-0"
              onClick={onOpenLibrary}
            >
              {BOARD_EMPTY_LIBRARY_ACTION}
              <ArrowRightIcon size={12} />
            </Button>
          </div>
          <div className="flex flex-wrap gap-1.5 px-1">
            {LIBRARY_STARTERS.map((name) => {
              const entry = libraryEntry(name);
              if (!entry) return null;
              const Icon = libraryEntryIcon(name);
              return (
                <button
                  key={name}
                  type="button"
                  className="flex items-center gap-1.5 rounded-full border border-(--gray-4) border-solid bg-(--gray-1) px-2.5 py-1 text-[12px] transition-colors hover:border-(--gray-6) hover:bg-(--gray-3)"
                  onClick={() => onAddFragment(name)}
                >
                  <Icon size={13} className="text-(--accent-11)" />
                  {entry.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
