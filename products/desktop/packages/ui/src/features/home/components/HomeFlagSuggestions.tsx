import { ArrowRightIcon, FlagIcon } from "@phosphor-icons/react";
import type { HomeFeatureFlag } from "@posthog/core/home/homeSchemas";
import { Badge, Button, Card } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useChannelMutations } from "@posthog/ui/features/canvas/hooks/useChannels";
import type { HomeFlagSuggestion } from "@posthog/ui/features/home/homeSuggestions";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

function rolloutLabel(flag: HomeFeatureFlag): string | null {
  if (!flag.active) return "Disabled";
  if (flag.rolloutPercentage == null) return null;
  return `${flag.rolloutPercentage}% rollout`;
}

/**
 * A flag, and the one move Home offers on it: give it a space, so the work
 * behind the flag has somewhere to happen. A flag whose space already exists
 * opens it instead.
 */
function FlagSuggestionCard({
  suggestion,
  onOpenSpace,
  onStartSpace,
  isStarting,
}: {
  suggestion: HomeFlagSuggestion;
  onOpenSpace: (channelId: string) => void;
  onStartSpace: (suggestion: HomeFlagSuggestion) => void;
  isStarting: boolean;
}) {
  const { flag, spaceName, existingSpace } = suggestion;
  const rollout = rolloutLabel(flag);

  return (
    <Card className="flex flex-row items-center gap-3 p-3">
      <FlagIcon size={16} className="shrink-0 text-muted-foreground" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium text-sm">{flag.key}</span>
          {rollout ? <Badge variant="default">{rollout}</Badge> : null}
          {flag.yours ? <Badge variant="info">Yours</Badge> : null}
        </div>
        <span className="truncate text-muted-foreground text-xs">
          {existingSpace
            ? `Already has #${existingSpace.name}`
            : `Starts #${spaceName}`}
          {flag.name !== flag.key ? ` · ${flag.name}` : ""}
        </span>
      </div>
      <div className="ml-auto shrink-0">
        {existingSpace ? (
          <Button
            variant="outline"
            onClick={() => onOpenSpace(existingSpace.id)}
          >
            Open space
            <ArrowRightIcon size={14} />
          </Button>
        ) : (
          <Button
            variant="primary"
            loading={isStarting}
            disabled={isStarting}
            onClick={() => onStartSpace(suggestion)}
          >
            Start a space
          </Button>
        )}
      </div>
    </Card>
  );
}

/**
 * Home's suggestions: recent feature flags with somewhere to go. Creating the
 * space stars it, the way the create form does, so it lands where the person
 * will find it again.
 */
export function HomeFlagSuggestions({
  suggestions,
}: {
  suggestions: HomeFlagSuggestion[];
}) {
  const navigate = useNavigate();
  const { createChannel } = useChannelMutations();
  // Which flag's space is being created, so only that card shows a spinner and
  // only that button locks.
  const [startingKey, setStartingKey] = useState<string | null>(null);

  const openSpace = (channelId: string) => {
    track(ANALYTICS_EVENTS.HOME_ACTION, {
      action_type: "open_space_from_flag",
    });
    void navigate({ to: "/website/$channelId", params: { channelId } });
  };

  const startSpace = async (suggestion: HomeFlagSuggestion) => {
    if (startingKey) return;
    setStartingKey(suggestion.flag.key);
    try {
      const channel = await createChannel(suggestion.spaceName, { star: true });
      track(ANALYTICS_EVENTS.HOME_ACTION, {
        action_type: "start_space_from_flag",
        success: true,
      });
      await navigate({
        to: "/website/$channelId",
        params: { channelId: channel.id },
      });
    } catch (error: unknown) {
      track(ANALYTICS_EVENTS.HOME_ACTION, {
        action_type: "start_space_from_flag",
        success: false,
      });
      toast.error("Couldn't start the space", {
        description: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setStartingKey(null);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      {suggestions.map((suggestion) => (
        <FlagSuggestionCard
          key={suggestion.flag.id}
          suggestion={suggestion}
          onOpenSpace={openSpace}
          onStartSpace={(next) => void startSpace(next)}
          isStarting={startingKey === suggestion.flag.key}
        />
      ))}
    </div>
  );
}
