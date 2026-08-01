import { ChatCircleIcon } from "@phosphor-icons/react";
import type { ScoutEmission } from "@posthog/api-client/posthog-client";
import { prettifyScoutSkillName } from "@posthog/core/scouts/scoutPresentation";
import { buildScoutFindingDiscussPrompt } from "@posthog/core/scouts/scoutPrompts";
import { Button } from "@posthog/quill";
import { Flex, Popover, Spinner, Text, TextArea } from "@radix-ui/themes";
import { useCallback, useMemo, useState } from "react";
import { useScoutChatTask } from "../hooks/useScoutChatTask";

const isMac =
  typeof navigator !== "undefined" && /Mac/i.test(navigator.platform);

/**
 * Per-finding "Discuss" CTA on a scout emission card: opens a popover for an
 * optional question, then fires a one-click auto-mode cloud task that digs into
 * this specific finding. Mirrors the inbox report Discuss flow.
 */
export function ScoutFindingDiscussButton({
  emission,
  skillName,
}: {
  emission: ScoutEmission;
  skillName: string;
}) {
  const [question, setQuestion] = useState("");
  const [open, setOpen] = useState(false);

  const displayName = useMemo(
    () => prettifyScoutSkillName(skillName),
    [skillName],
  );

  const prompt = useMemo(
    () =>
      buildScoutFindingDiscussPrompt({
        skillName,
        displayName,
        runId: emission.run_id,
        findingId: emission.finding_id,
        description: emission.description,
        severity: emission.severity,
        confidence: emission.confidence,
        question: question.trim() || undefined,
      }),
    [
      skillName,
      displayName,
      emission.run_id,
      emission.finding_id,
      emission.description,
      emission.severity,
      emission.confidence,
      question,
    ],
  );

  const { runTask, isRunning } = useScoutChatTask({
    prompt,
    taskLabel: "finding discussion",
    loggerScope: "scout-finding-discuss",
    chatType: "finding_discuss",
    surface: "scout_detail",
    skillName,
  });

  const submit = useCallback(() => {
    if (isRunning) return;
    // A question is optional: an empty submit resolves to the "brief readout"
    // prompt. `runTask` closes over the current prompt, so clearing state
    // afterwards is safe and leaves the popover ready for next time.
    void runTask();
    setQuestion("");
    setOpen(false);
  }, [isRunning, runTask]);

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setQuestion("");
      }}
    >
      <Popover.Trigger>
        <button
          type="button"
          disabled={isRunning}
          title="Discuss this finding with your agent"
          className="inline-flex shrink-0 items-center gap-1 text-[11px] text-accent-11 no-underline transition-colors hover:text-accent-12 disabled:cursor-default disabled:opacity-60"
        >
          {isRunning ? <Spinner size="1" /> : <ChatCircleIcon size={11} />}
          Discuss
        </button>
      </Popover.Trigger>
      <Popover.Content
        align="start"
        side="bottom"
        sideOffset={6}
        className="w-[420px] border border-(--gray-6) bg-(--color-panel-solid) p-3 shadow-6"
      >
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
        >
          <TextArea
            aria-label="Question to discuss about this finding"
            autoFocus
            placeholder="Ask about this finding… (optional)"
            resize="vertical"
            rows={5}
            size="2"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <Flex justify="between" align="center" gap="2">
            <Text size="1" color="gray">
              {isMac ? "⌘↵" : "Ctrl+↵"} to send
            </Text>
            <Flex gap="2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                disabled={isRunning}
              >
                Discuss
              </Button>
            </Flex>
          </Flex>
        </form>
      </Popover.Content>
    </Popover.Root>
  );
}
