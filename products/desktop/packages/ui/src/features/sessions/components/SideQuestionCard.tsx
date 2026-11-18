import { ChatCircleDots, X } from "@phosphor-icons/react";
import {
  Button,
  Text,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { useSideQuestionStore } from "@posthog/ui/features/sessions/sideQuestionStore";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";

interface SideQuestionCardProps {
  taskId: string;
  /** The task's current run. An entry asked against a prior run is hidden. */
  taskRunId?: string;
}

/**
 * Ephemeral "/btw" side-question card pinned above the composer. The exchange
 * lives only in view state — it is never part of the session transcript — so
 * dismissing it leaves no trace. Session summaries have their own panel.
 */
export function SideQuestionCard({ taskId, taskRunId }: SideQuestionCardProps) {
  const entry = useSideQuestionStore((s) => s.byTaskId[taskId]);
  const dismiss = useSideQuestionStore((s) => s.dismiss);

  if (!entry || entry.taskRunId !== taskRunId) return null;
  if (entry.kind === "summary") return null;

  const title = entry.label ?? entry.question;

  return (
    <div className="mb-2 rounded-(--radius-lg) border border-(--gray-5) bg-(--gray-2) px-3 py-2">
      <div className="flex items-center gap-2">
        <ChatCircleDots size={14} className="shrink-0 text-muted-foreground" />
        <Text
          title={title}
          className="min-w-0 flex-1 truncate font-medium text-[13px] text-foreground"
        >
          {title}
        </Text>
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                type="button"
                variant="link-muted"
                size="icon-sm"
                aria-label="Dismiss side question"
                className="shrink-0"
                onClick={() => dismiss(taskId)}
              >
                <X size={12} />
              </Button>
            }
          />
          <TooltipContent side="top">Dismiss</TooltipContent>
        </Tooltip>
      </div>
      <output className="mt-1 block pl-6">
        {entry.status === "pending" && (
          <div className="flex items-center gap-2">
            <Spinner size="md" className="text-muted-foreground" />
            <Text className="text-[13px] text-muted-foreground">
              Answering…
            </Text>
          </div>
        )}
        {entry.status === "done" && (
          <div className="max-h-64 overflow-y-auto text-[13px] text-foreground">
            <MarkdownRenderer content={entry.answer} />
          </div>
        )}
        {entry.status === "error" && (
          <Text className="text-(--red-11) text-[13px]">{entry.error}</Text>
        )}
      </output>
    </div>
  );
}
