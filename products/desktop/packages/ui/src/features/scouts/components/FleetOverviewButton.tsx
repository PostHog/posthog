import { SparkleIcon } from "@phosphor-icons/react";
import { SCOUT_FLEET_OVERVIEW_PROMPT } from "@posthog/core/scouts/scoutPrompts";
import { Button } from "@posthog/quill";
import { useScoutChatTask } from "../hooks/useScoutChatTask";

/** Starts a cloud task that reviews the whole fleet and opens it. */
export function FleetOverviewButton() {
  const { runTask, isRunning } = useScoutChatTask({
    prompt: SCOUT_FLEET_OVERVIEW_PROMPT,
    taskLabel: "fleet overview",
    loggerScope: "scout-fleet-overview",
    chatType: "fleet_overview",
    surface: "fleet_list",
  });
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => void runTask()}
      disabled={isRunning}
      data-attr="agents-ask-about-fleet"
    >
      <SparkleIcon size={13} />
      {isRunning ? "Starting…" : "Ask about the fleet"}
    </Button>
  );
}
