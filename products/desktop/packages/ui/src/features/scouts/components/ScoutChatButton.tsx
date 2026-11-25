import { SparkleIcon } from "@phosphor-icons/react";
import { buildScoutCheckinPrompt } from "@posthog/core/scouts/scoutPrompts";
import { Button } from "@posthog/quill";
import type { ScoutSurface } from "@posthog/shared";
import { prettifyScoutSkillName } from "@posthog/shared/scout-names";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { useMemo } from "react";
import { useScoutChatTask } from "../hooks/useScoutChatTask";

/**
 * One-click check-in on a scout: creates an auto-mode cloud task that asks
 * PostHog about this scout and opens it. Icon-only unless a label is given.
 */
export function ScoutChatButton({
  skillName,
  displayName,
  surface,
  label,
}: {
  skillName: string;
  displayName: string;
  surface: ScoutSurface;
  label?: string;
}) {
  // Any config writer can set `displayName` to free text, so the agent prompt uses the validated slug.
  const prompt = useMemo(
    () => buildScoutCheckinPrompt(skillName, prettifyScoutSkillName(skillName)),
    [skillName],
  );
  const { runTask, isRunning } = useScoutChatTask({
    prompt,
    taskLabel: "agent check-in",
    loggerScope: "scout-checkin",
    chatType: "scout_checkin",
    surface,
    skillName,
  });

  if (label) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void runTask()}
        disabled={isRunning}
        data-attr="scout-discuss"
      >
        <SparkleIcon size={13} />
        {isRunning ? "Starting…" : label}
      </Button>
    );
  }

  return (
    <Tooltip content="Ask PostHog about this agent">
      <Button
        type="button"
        variant="default"
        size="icon-sm"
        onClick={() => void runTask()}
        disabled={isRunning}
        aria-label={`Ask PostHog about the ${displayName} agent`}
        className={isRunning ? "animate-pulse text-(--iris-9)" : undefined}
        data-attr="scout-discuss"
      >
        <SparkleIcon size={14} />
      </Button>
    </Tooltip>
  );
}
