import { ArrowUpIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { useState } from "react";
import { useLoopBuilderTask } from "../hooks/useLoopBuilderTask";

const DEFAULT_EXAMPLES = [
  "Summarize my open PRs every weekday morning",
  "Triage new issues and flag duplicates",
  "Draft release notes when a PR merges to main",
];

/** The "describe what you want and an agent builds it" prompt box. Passing `context` attaches
 * the built loop to it. `quickStarts` replaces the generic example chips above the box with
 * labeled starters (each fills the box for the user to finish). */
export function LoopBuilderComposer({
  context,
  placeholder = "What do you want automated?",
  quickStarts,
}: {
  context?: { folderId: string; name: string };
  placeholder?: string;
  quickStarts?: { label: string; prompt: string }[];
}) {
  const [prompt, setPrompt] = useState("");
  const { runTask, isRunning } = useLoopBuilderTask(context);

  const chips =
    quickStarts ??
    DEFAULT_EXAMPLES.map((example) => ({ label: example, prompt: example }));

  const start = () => {
    const text = prompt.trim();
    if (!text || isRunning) return;
    void runTask(text);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {chips.map((chip) => (
          <button
            key={chip.label}
            type="button"
            disabled={isRunning}
            onClick={() => setPrompt(chip.prompt)}
            className="rounded-full border border-gray-5 bg-gray-2 px-3 py-1 text-gray-11 text-xs transition-colors hover:border-gray-7 hover:bg-gray-3 disabled:opacity-60"
          >
            {chip.label}
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-2 rounded-(--radius-4) border border-border bg-(--color-panel-solid) p-3 transition-colors focus-within:border-(--gray-8)">
        <textarea
          value={prompt}
          rows={2}
          disabled={isRunning}
          placeholder={placeholder}
          className="w-full resize-none bg-transparent text-[13px] text-gray-12 leading-relaxed outline-none placeholder:text-gray-9 disabled:opacity-60"
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (
              e.key === "Enter" &&
              !e.shiftKey &&
              !e.nativeEvent.isComposing
            ) {
              e.preventDefault();
              start();
            }
          }}
        />
        <div className="flex items-center justify-between gap-3">
          <span className="text-[11px] text-gray-9">
            An agent builds the loop with you, then creates it on your
            confirmation
          </span>
          <Button
            variant="primary"
            size="icon-sm"
            aria-label="Build loop with an agent"
            loading={isRunning}
            disabled={!prompt.trim() || isRunning}
            onClick={start}
          >
            <ArrowUpIcon size={13} weight="bold" />
          </Button>
        </div>
      </div>
    </div>
  );
}
