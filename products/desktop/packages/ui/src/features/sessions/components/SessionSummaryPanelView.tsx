import { TextAlignLeft } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { MarkdownRenderer } from "../../editor/components/MarkdownRenderer";

export type SessionSummaryState =
  | { status: "pending" }
  | { status: "done"; summary: string }
  | { status: "error"; error: string };

interface SessionSummaryPanelViewProps {
  title: string;
  state: SessionSummaryState;
  onCopy: () => void;
  onRetry: () => void;
  onDismiss: () => void;
}

/** Rough size of the text, so a person knows what they are about to paste. */
function wordCount(summary: string): number {
  return summary.trim().split(/\s+/).length;
}

/** Past this the text outgrows the panel, so the cut edge needs a signal. */
const SCROLLS_ABOVE_WORDS = 90;

/**
 * The summary dock, in the composer column. Presentation only: the container
 * owns the store, the clipboard, and the analytics.
 */
export function SessionSummaryPanelView({
  title,
  state,
  onCopy,
  onRetry,
  onDismiss,
}: SessionSummaryPanelViewProps) {
  return (
    <div className="mb-2 overflow-hidden rounded-(--radius-lg) border border-(--gray-4) bg-(--gray-2)">
      <div className="flex items-center gap-2 px-3 pt-2 pb-1">
        <TextAlignLeft size={14} className="shrink-0 text-muted-foreground" />
        <Text className="min-w-0 truncate font-medium text-[13px] text-foreground">
          {title}
        </Text>
        {state.status === "done" && (
          <Text className="shrink-0 text-[11.5px] text-muted-foreground tabular-nums">
            {wordCount(state.summary)} words
          </Text>
        )}
        <div className="ml-auto flex shrink-0 items-center gap-1">
          {state.status === "done" && (
            <Button type="button" variant="outline" size="xs" onClick={onCopy}>
              Copy
            </Button>
          )}
          {state.status === "error" && (
            <Button type="button" variant="outline" size="xs" onClick={onRetry}>
              Try again
            </Button>
          )}
          <Button
            type="button"
            variant="link-muted"
            size="xs"
            onClick={onDismiss}
          >
            {state.status === "pending" ? "Stop waiting" : "Dismiss"}
          </Button>
        </div>
      </div>
      <output className="block px-3 pb-2.5">
        {state.status === "pending" && (
          <div className="flex items-start gap-2">
            <Spinner
              size={13}
              className="mt-0.5 shrink-0 text-muted-foreground"
            />
            <Text className="text-[12.5px] text-muted-foreground">
              Writing the summary. About 30 seconds. You can keep working, and
              the agent finishes the turn either way.
            </Text>
          </div>
        )}
        {state.status === "done" && (
          <div className="relative">
            <div className="max-h-52 overflow-y-auto text-[13px] text-foreground">
              <MarkdownRenderer content={state.summary} />
            </div>
            {wordCount(state.summary) > SCROLLS_ABOVE_WORDS && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-7 bg-linear-to-t from-(--gray-2) to-transparent" />
            )}
          </div>
        )}
        {state.status === "error" && (
          <Text className="text-(--red-11) text-[12.5px]">
            Couldn't write the summary. {state.error}
          </Text>
        )}
      </output>
    </div>
  );
}
