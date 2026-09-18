import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { useService } from "@posthog/di/react";
import { Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  DISCORD_PRESENCE_CLIENT,
  type DiscordPresenceClient,
  type DiscordPresenceState,
} from "@posthog/ui/features/discord-presence/identifiers";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { track } from "@posthog/ui/shell/analytics";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { useEffect, useState } from "react";
import { DiscordPresencePreview } from "./DiscordPresencePreview";

const DISCORD_DOCS_URL =
  "https://posthog.com/docs/libraries/discord?tab=Desktop";

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

  const statusDescription = !enabled ? (
    "Show what you're working on in PostHog on your profile"
  ) : !configured ? (
    <span className="text-(--amber-11)">
      No Discord application is configured for this build, so nothing will
      appear yet.
    </span>
  ) : connected ? (
    <span className="text-(--green-11)">Connected to Discord</span>
  ) : (
    <span className="text-(--amber-11)">
      Waiting for Discord (desktop app needs to be running)...
    </span>
  );

  return (
    <div className="flex flex-col gap-7">
      <SettingsCard>
        <SettingsCardRow label="Rich Presence" description={statusDescription}>
          <Switch
            size="sm"
            checked={enabled}
            onCheckedChange={handleEnabledChange}
          />
        </SettingsCardRow>
      </SettingsCard>

      {enabled ? (
        <SettingsSection
          label="Privacy"
          description="What the Rich Presence card reveals about your session"
        >
          <SettingsCard>
            <SettingsCardRow
              label="Show task title"
              description="Include the focused task's title"
            >
              <Switch
                size="sm"
                checked={state?.showTaskTitle ?? false}
                onCheckedChange={handleShowTaskTitleChange}
              />
            </SettingsCardRow>
            <SettingsCardRow
              label="Show repository name"
              description="Include the repository (org/repo) you're working in"
            >
              <Switch
                size="sm"
                checked={state?.showRepoName ?? false}
                onCheckedChange={handleShowRepoNameChange}
              />
            </SettingsCardRow>
          </SettingsCard>
        </SettingsSection>
      ) : null}

      <DiscordPresencePreview
        enabled={enabled}
        showTaskTitle={state?.showTaskTitle ?? false}
        showRepoName={state?.showRepoName ?? false}
      />

      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => void openUrlInBrowser(DISCORD_DOCS_URL)}
          className="inline-flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-muted-foreground text-xs no-underline hover:text-foreground"
        >
          Learn about the Discord integration
          <ArrowSquareOutIcon size={11} />
        </button>
      </div>
    </div>
  );
}
