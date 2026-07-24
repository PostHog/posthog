import { useService } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  DISCORD_PRESENCE_CLIENT,
  type DiscordPresenceClient,
  type DiscordPresenceState,
} from "@posthog/ui/features/discord-presence/identifiers";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { track } from "@posthog/ui/shell/analytics";
import { Flex, Switch, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";
import { DiscordPresencePreview } from "./DiscordPresencePreview";

// Fallback used for optimistic toggle updates that fire before the initial
// getState resolves, so the Switch reflects the change immediately instead of
// appearing stuck at its default. The status subscription reconciles the
// remaining fields (connected, configured) right after.
const DEFAULT_STATE: DiscordPresenceState = {
  enabled: false,
  connected: false,
  configured: false,
  showTaskTitle: false,
  showRepoName: false,
};

export function DiscordSettings() {
  const client = useService<DiscordPresenceClient>(DISCORD_PRESENCE_CLIENT);
  const [state, setState] = useState<DiscordPresenceState | null>(null);

  useEffect(() => {
    let active = true;
    client.getState().then((next) => {
      if (active) setState(next);
    });
    // The host emits status changes (connect/disconnect, toggle writes) so the
    // panel reflects the live connection without polling.
    const unsubscribe = client.onStatusChanged(setState);
    return () => {
      active = false;
      unsubscribe();
    };
  }, [client]);

  const enabled = state?.enabled ?? false;
  const configured = state?.configured ?? false;
  const connected = state?.connected ?? false;

  const handleEnabledChange = (checked: boolean) => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "discord_presence_enabled",
      new_value: checked,
      old_value: enabled,
    });
    setState((prev) => ({ ...(prev ?? DEFAULT_STATE), enabled: checked }));
    client.setEnabled(checked);
  };

  const handleShowTaskTitleChange = (checked: boolean) => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "discord_presence_show_task_title",
      new_value: checked,
      old_value: state?.showTaskTitle ?? false,
    });
    setState((prev) => ({
      ...(prev ?? DEFAULT_STATE),
      showTaskTitle: checked,
    }));
    client.setShowTaskTitle(checked);
  };

  const handleShowRepoNameChange = (checked: boolean) => {
    track(ANALYTICS_EVENTS.SETTING_CHANGED, {
      setting_name: "discord_presence_show_repo_name",
      new_value: checked,
      old_value: state?.showRepoName ?? false,
    });
    setState((prev) => ({ ...(prev ?? DEFAULT_STATE), showRepoName: checked }));
    client.setShowRepoName(checked);
  };

  return (
    <Flex direction="column">
      <SettingRow
        label="Rich Presence"
        description="Show what you're working on in PostHog on your profile"
        noBorder
      >
        <Switch
          checked={enabled}
          onCheckedChange={handleEnabledChange}
          size="1"
        />
      </SettingRow>

      {enabled && (
        <>
          {!configured ? (
            <Text color="yellow" className="-mt-3 pb-3 text-[13px]">
              No Discord application is configured for this build, so nothing
              will appear yet.
            </Text>
          ) : (
            <Text
              color={connected ? "green" : "amber"}
              className="-mt-3 pb-3 text-[13px]"
            >
              {connected
                ? "Connected to Discord"
                : "Waiting for Discord (desktop app needs to be running)..."}
            </Text>
          )}

          <Text className="block border-gray-6 border-t pt-4 font-medium text-sm">
            Privacy
          </Text>

          <SettingRow
            label="Show task title"
            description="Include the focused task's title"
          >
            <Switch
              checked={state?.showTaskTitle ?? false}
              onCheckedChange={handleShowTaskTitleChange}
              size="1"
            />
          </SettingRow>

          <SettingRow
            label="Show repository name"
            description="Include the repository (org/repo) you're working in"
            noBorder
          >
            <Switch
              checked={state?.showRepoName ?? false}
              onCheckedChange={handleShowRepoNameChange}
              size="1"
            />
          </SettingRow>
        </>
      )}

      <DiscordPresencePreview
        enabled={enabled}
        showTaskTitle={state?.showTaskTitle ?? false}
        showRepoName={state?.showRepoName ?? false}
      />
    </Flex>
  );
}
