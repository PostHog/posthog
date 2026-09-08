import { DotsThree, GameController, Pause, Play } from "@phosphor-icons/react";
import { SettingsSection } from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";
import { Flex, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import posthogIcon from "../../auth/assets/posthog-icon.svg";

interface DiscordPresencePreviewProps {
  /** Mirrors the "Show task title" toggle. */
  showTaskTitle: boolean;
  /** Mirrors the "Show repository name" toggle. */
  showRepoName: boolean;
  /** When false the card is dimmed to read as an inactive teaser. */
  enabled: boolean;
}

// Illustrative data — what a session looks like on a Discord profile.
const SAMPLE_TASK_TITLE = "Repository overview";
const SAMPLE_REPO = "posthog/posthog";

function formatElapsed(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * A faithful mock of the Discord Rich Presence card, built from app primitives
 * so it tracks the theme. It reacts to the privacy toggles (so users see what
 * each reveals) and lets them flip between the running and idle states.
 */
export function DiscordPresencePreview({
  showTaskTitle,
  showRepoName,
  enabled,
}: DiscordPresencePreviewProps) {
  const [running, setRunning] = useState(true);
  const [elapsed, setElapsed] = useState(197); // 3:17, like a session in progress

  // When the integration goes dormant, fall back to the idle state. Adjust
  // during render (not in an effect) so the card never flashes the stale
  // "running" state for a frame before settling.
  const [prevEnabled, setPrevEnabled] = useState(enabled);
  if (enabled !== prevEnabled) {
    setPrevEnabled(enabled);
    if (!enabled) {
      setRunning(false);
    }
  }

  // While enabled, tick the elapsed timer so the card feels live, the way
  // Discord shows it.
  useEffect(() => {
    if (!enabled) {
      return;
    }
    const interval = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(interval);
  }, [enabled]);

  const details = showTaskTitle
    ? `Working on "${SAMPLE_TASK_TITLE}"`
    : "Working on a task";
  const statusPart = running ? "agent running" : "reviewing";
  const state = showRepoName ? `${SAMPLE_REPO} · ${statusPart}` : statusPart;

  return (
    <SettingsSection
      label="Preview"
      description="What your Discord profile shows while you work"
      action={
        <SettingsSegmented
          value={running ? "running" : "idle"}
          options={[
            { value: "running", label: "Running" },
            { value: "idle", label: "Idle" },
          ]}
          onValueChange={(value) => setRunning(value === "running")}
          ariaLabel="Preview state"
          disabled={!enabled}
        />
      }
    >
      <div
        className={`max-w-[380px] rounded-xl border border-border bg-gray-2 px-4 py-3 ${
          enabled ? "" : "pointer-events-none opacity-50"
        }`}
      >
        <Flex align="center" justify="between">
          <Text className="font-semibold text-[12px] text-muted-foreground">
            Playing
          </Text>
          <DotsThree
            size={18}
            weight="bold"
            className="text-muted-foreground"
          />
        </Flex>

        <Flex align="start" gap="3" className="mt-2">
          <div className="relative shrink-0">
            <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-lg bg-[#eeefe9]">
              <img src={posthogIcon} alt="" className="h-auto w-12" />
            </div>
            <div
              className="-right-1.5 -bottom-1.5 absolute flex h-7 w-7 items-center justify-center rounded-full ring-4 ring-gray-2"
              style={{ backgroundColor: running ? "#1D4AFF" : "#DC9300" }}
            >
              {running ? (
                <Play size={13} weight="fill" className="ml-[2px] text-white" />
              ) : (
                <Pause size={13} weight="fill" className="text-white" />
              )}
            </div>
          </div>

          <Flex direction="column" className="min-w-0 gap-0">
            <Text className="font-bold text-[15px] text-foreground">
              PostHog
            </Text>
            <Text truncate className="text-[13px] text-foreground">
              {details}
            </Text>
            <Text truncate className="text-[13px] text-muted-foreground">
              {state}
            </Text>
            <Flex align="center" gap="1" className="mt-0.5 text-(--green-11)">
              <GameController size={15} />
              <Text className="text-(--green-11) text-[12px]">
                {formatElapsed(elapsed)} elapsed
              </Text>
            </Flex>
          </Flex>
        </Flex>
      </div>
    </SettingsSection>
  );
}
