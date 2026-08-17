import { useServiceOptional } from "@posthog/di/react";
import { Switch } from "@posthog/quill";
import { RepositoriesField } from "@posthog/ui/features/canvas/components/RepositoriesField";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskSettingsPatch,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { QuickAskShortcutSetting } from "@posthog/ui/features/settings/sections/QuickAskShortcutSetting";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { Flex, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";

/** Empty channel id: the backend files new threads into the personal space. */
const PERSONAL = "";

export function QuickAskSettings() {
  const client = useServiceOptional<QuickAskSettingsClient>(
    QUICK_ASK_SETTINGS_CLIENT,
  );
  const [state, setState] = useState<QuickAskState | null>(null);

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

  const channels = useAuthenticatedQuery(
    ["quick-ask-settings-channels"],
    (apiClient) => apiClient.getTaskChannels(),
    { staleTime: 60_000, refetchOnWindowFocus: false },
  );

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

  const spaceOptions = [
    { value: PERSONAL, label: "Personal" },
    ...(channels.data ?? [])
      .filter((channel) => channel.channel_type === "public")
      .map((channel) => ({ value: channel.id, label: channel.name })),
  ];
  const selectedSpace = spaceOptions.some(
    (option) => option.value === state.defaultChannelId,
  )
    ? state.defaultChannelId
    : PERSONAL;
  const spaceRepositories =
    (channels.data ?? []).find(
      (channel) => channel.id === state.defaultChannelId,
    )?.repositories ?? [];

  return (
    <Flex direction="column">
      <QuickAskShortcutSetting />

      <SettingRow
        label="Default space"
        description="New quick-ask threads file into this space."
      >
        <SettingsOptionSelect
          value={selectedSpace}
          options={spaceOptions}
          onValueChange={(value) => apply({ defaultChannelId: value })}
          ariaLabel="Default space"
        />
      </SettingRow>

      <SettingRow
        label="Default repositories"
        description={
          state.defaultRepositories.length === 0 && spaceRepositories.length > 0
            ? `None of your own; the space brings ${spaceRepositories.join(", ")}.`
            : "Cloned into the sandbox for every new thread. Leave empty for data-only answers, or to use the space's repositories."
        }
      >
        <RepositoriesField
          selected={state.defaultRepositories}
          integrationId={state.defaultGithubIntegrationId || null}
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
        />
      </SettingRow>
    </Flex>
  );
}
