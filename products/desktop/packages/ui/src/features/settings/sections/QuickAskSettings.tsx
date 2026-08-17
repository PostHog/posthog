import { useServiceOptional } from "@posthog/di/react";
import { Switch } from "@posthog/quill";
import { RepositoriesField } from "@posthog/ui/features/canvas/components/RepositoriesField";
import { SpaceSelect } from "@posthog/ui/features/canvas/components/SpaceSelect";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskSettingsPatch,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { QuickAskShortcutSetting } from "@posthog/ui/features/settings/sections/QuickAskShortcutSetting";
import { Flex, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";

export function QuickAskSettings() {
  const client = useServiceOptional<QuickAskSettingsClient>(
    QUICK_ASK_SETTINGS_CLIENT,
  );
  const [state, setState] = useState<QuickAskState | null>(null);
  const { channels } = useChannels();

  useEffect(() => {
    if (!client) return;
    let active = true;
    client.getState().then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [client]);

  if (!client || !state?.enabled) {
    return (
      <Text className="text-(--gray-11) text-sm">
        The quick-ask panel is not available in this build.
      </Text>
    );
  }

  const apply = (patch: QuickAskSettingsPatch): void => {
    void client.setSettings(patch).then(setState);
  };

  const personal = channels.find(
    (channel) => channel.channelType === "personal",
  );
  // The stored empty id means the personal space (the backend's default).
  const selectedSpaceId = state.defaultChannelId || (personal?.id ?? "");
  const selectedSpace = channels.find(
    (channel) => channel.id === selectedSpaceId,
  );
  const spaceRepositories =
    state.defaultChannelId && selectedSpace?.channelType !== "personal"
      ? (selectedSpace?.repositories ?? [])
      : [];
  const off = !state.active;

  return (
    <Flex direction="column">
      <SettingRow
        label="Enable quick ask"
        description="The floating panel and its global shortcut. Turning this off frees the shortcut."
      >
        <Switch
          size="sm"
          checked={state.active}
          onCheckedChange={(checked) => apply({ active: checked })}
          aria-label="Enable quick ask"
        />
      </SettingRow>

      <div className={off ? "pointer-events-none opacity-50" : undefined}>
        <QuickAskShortcutSetting disabled={off} />

        <SettingRow
          label="Default space"
          description="New quick-ask threads file into this space."
        >
          <SpaceSelect
            value={selectedSpaceId}
            disabled={off}
            onChange={(channelId) => {
              const picked = channels.find(
                (channel) => channel.id === channelId,
              );
              apply({
                defaultChannelId:
                  picked?.channelType === "personal" ? "" : channelId,
              });
            }}
          />
        </SettingRow>

        <SettingRow
          label="Default repositories"
          description={
            state.defaultRepositories.length === 0 &&
            spaceRepositories.length > 0
              ? `None of your own; the space brings ${spaceRepositories.join(", ")}.`
              : "Cloned into the sandbox for every new thread. Leave empty for data-only answers, or to use the space's repositories."
          }
        >
          <RepositoriesField
            selected={state.defaultRepositories}
            integrationId={state.defaultGithubIntegrationId || null}
            disabled={off}
            onChange={(repositories, integrationId) =>
              apply({
                defaultRepositories: repositories,
                defaultGithubIntegrationId: integrationId ?? 0,
              })
            }
          />
        </SettingRow>

        <SettingRow
          label="Warm a sandbox on summon"
          description="Boots the agent while you type, so the first answer starts at model speed. Uses compute for summons that never ask."
          noBorder
        >
          <Switch
            size="sm"
            checked={state.warmOnSummon}
            onCheckedChange={(checked) => apply({ warmOnSummon: checked })}
            aria-label="Warm a sandbox on summon"
            disabled={off}
          />
        </SettingRow>
      </div>
    </Flex>
  );
}
