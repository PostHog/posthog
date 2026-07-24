import { ArrowUpIcon } from "@phosphor-icons/react";
import { Flex, IconButton, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useLoopBuilderTask } from "../hooks/useLoopBuilderTask";

const DEFAULT_EXAMPLES = [
  "Summarize my open PRs every weekday morning",
  "Triage new issues and flag duplicates",
  "Draft release notes when a PR merges to main",
];

/** The "describe what you want and an agent builds it" prompt box. Passing `context` attaches
 * the built loop to it. `quickStarts` replaces the generic example chips above the box with
 * labeled starters (each fills the box for the user to finish). `disabledReason`, when set, blocks
 * the whole composer and shows that reason instead of the helper text (e.g. the project loop cap). */
export function LoopBuilderComposer({
  context,
  placeholder = "What do you want automated?",
  quickStarts,
  disabledReason,
}: {
  context?: { folderId: string; name: string };
  placeholder?: string;
  quickStarts?: { label: string; prompt: string }[];
  disabledReason?: string | null;
}) {
  const [prompt, setPrompt] = useState("");
  const { runTask, isRunning } = useLoopBuilderTask(context);

  const blocked = Boolean(disabledReason);
  const chips =
    quickStarts ??
    DEFAULT_EXAMPLES.map((example) => ({ label: example, prompt: example }));

  const start = () => {
    const text = prompt.trim();
    if (!text || isRunning || blocked) return;
    void runTask(text);
  };

  return (
    <Flex direction="column" gap="2">
      <Flex gap="2" wrap="wrap">
        {chips.map((chip) => (
          <button
            key={chip.label}
            type="button"
            disabled={isRunning || blocked}
            onClick={() => setPrompt(chip.prompt)}
            className="rounded-full border border-gray-5 bg-gray-2 px-3 py-1 text-gray-11 text-xs transition-colors hover:border-gray-7 hover:bg-gray-3 disabled:opacity-60"
          >
            {chip.label}
          </button>
        ))}
      </Flex>
      <Flex
        direction="column"
        gap="2"
        className="rounded-(--radius-4) border border-border bg-(--color-panel-solid) p-3 transition-colors focus-within:border-(--gray-8)"
      >
        <textarea
          value={prompt}
          rows={2}
          disabled={isRunning || blocked}
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
        <Flex align="center" justify="between" gap="3">
          <Text
            className={`text-[11px] ${blocked ? "text-(--amber-11)" : "text-gray-9"}`}
          >
            {disabledReason ??
              "An agent builds the loop with you, then creates it on your confirmation"}
          </Text>
          <IconButton
            variant="solid"
            size="1"
            aria-label="Build loop with an agent"
            loading={isRunning}
            disabled={!prompt.trim() || isRunning || blocked}
            onClick={start}
          >
            <ArrowUpIcon size={13} weight="bold" />
          </IconButton>
        </Flex>
      </Flex>
    </Flex>
  );
}
