import { SparkleIcon } from "@phosphor-icons/react";
import { buildScoutAuthorPrompt } from "@posthog/core/scouts/scoutPrompts";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Textarea,
} from "@posthog/quill";
import { useMemo, useState } from "react";
import { useScoutChatTask } from "../hooks/useScoutChatTask";

const EXAMPLES = [
  "Errors that spike after a deploy",
  "Experiments past their end date",
  "Support tickets about billing",
];

/**
 * Describe an agent in a sentence; PostHog drafts it as a `signals-scout-*`
 * skill in a cloud task and opens that task for review.
 */
export function NewAgentDialog({
  open,
  onOpenChange,
  initialBrief = "",
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** What the box starts with, so a suggestion opens with its own brief in it. */
  initialBrief?: string;
}) {
  // Keyed on the brief by the caller, so a second suggestion refills the box
  // rather than leaving the first one in it.
  const [brief, setBrief] = useState(initialBrief);
  const prompt = useMemo(() => buildScoutAuthorPrompt(brief), [brief]);
  const { runTask, isRunning } = useScoutChatTask({
    prompt,
    taskLabel: "agent draft",
    loggerScope: "scout-author",
    chatType: "author_scout",
    surface: "fleet_list",
  });

  const submit = async () => {
    if (await runTask()) {
      onOpenChange(false);
      setBrief("");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>New agent</DialogTitle>
          <DialogDescription>
            Say what to watch and what to do when it finds something. PostHog
            drafts the agent in a task and opens it for you.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-2 bg-transparent">
          <Textarea
            value={brief}
            onChange={(event) => setBrief(event.target.value)}
            placeholder="Watch accounts on the Scale plan whose weekly active users drop 30% in two weeks. Send one signal per account with a suggested play."
            rows={4}
            autoFocus
            aria-label="What the agent should do"
            className="bg-(--color-panel-solid) placeholder:text-gray-9"
            data-attr="new-agent-brief"
          />
          <p className="text-[11.5px] text-gray-10">
            Try:{" "}
            {EXAMPLES.map((example, index) => (
              <span key={example}>
                {index > 0 ? " · " : null}
                <button
                  type="button"
                  onClick={() => setBrief(example)}
                  className="text-gray-11 underline decoration-(--gray-7) underline-offset-2 hover:text-gray-12"
                >
                  {example}
                </button>
              </span>
            ))}
          </p>
        </DialogBody>
        <DialogFooter>
          <span className="mr-auto text-[11.5px] text-gray-10">
            New agents start as a dry run.
          </span>
          <Button
            type="button"
            variant="default"
            size="sm"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => void submit()}
            disabled={isRunning || !brief.trim()}
            data-attr="new-agent-draft"
          >
            <SparkleIcon size={13} />
            {isRunning ? "Starting…" : "Draft agent"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
