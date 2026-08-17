import { useServiceOptional } from "@posthog/di/react";
import { Switch } from "@posthog/quill";
import {
  type Adapter,
  DEFAULT_CODEX_MODEL,
  DEFAULT_GATEWAY_MODEL,
  getReasoningEffortOptions,
  isRestrictedModelOption,
} from "@posthog/shared";
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
import { SettingsOptionSelect } from "@posthog/ui/features/settings/SettingsOptionSelect";
import { QuickAskShortcutSetting } from "@posthog/ui/features/settings/sections/QuickAskShortcutSetting";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { Flex, Text } from "@radix-ui/themes";
import { useEffect, useState } from "react";

const ADAPTER_OPTIONS = [
  { value: "", label: "Claude (default)" },
  { value: "codex", label: "Codex" },
];

export function QuickAskSettings() {
  const client = useServiceOptional<QuickAskSettingsClient>(
    QUICK_ASK_SETTINGS_CLIENT,
  );
  const [state, setState] = useState<QuickAskState | null>(null);
  const { channels } = useChannels();
  const adapterForQuery: Adapter =
    state?.defaultAdapter === "codex" ? "codex" : "claude";
  const models = useAuthenticatedQuery(
    ["quick-ask-settings-models", adapterForQuery],
    async (apiClient) => {
      const options =
        await apiClient.getCloudTaskConfigOptions(adapterForQuery);
      return (
        options.find((option) => option.category === "model")?.options ?? []
      );
    },
    { staleTime: 5 * 60 * 1000, refetchOnWindowFocus: false },
  );

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
  const adapter: Adapter =
    state.defaultAdapter === "codex" ? "codex" : "claude";
  const effortModel =
    state.defaultModel ||
    (adapter === "codex" ? DEFAULT_CODEX_MODEL : DEFAULT_GATEWAY_MODEL);
  const modelOptions = [
    { value: "", label: "Harness default" },
    ...(models.data ?? [])
      .filter((option) => !isRestrictedModelOption(option._meta))
      .map((option) => ({ value: option.value, label: option.name })),
  ];
  const effortOptions = [
    { value: "", label: "Default" },
    ...(getReasoningEffortOptions(adapter, effortModel) ?? []).map(
      (option) => ({ value: option.value, label: option.name }),
    ),
  ];

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
          label="Default harness"
          description="The agent that answers quick-ask questions."
        >
          <SettingsOptionSelect
            value={state.defaultAdapter}
            options={ADAPTER_OPTIONS}
            onValueChange={(value) =>
              apply({
                defaultAdapter: value,
                defaultModel: "",
                defaultEffort: "",
              })
            }
            ariaLabel="Default harness"
            disabled={off}
          />
        </SettingRow>

        <SettingRow
          label="Default model"
          description="Follows the harness default when unset."
        >
          <SettingsOptionSelect
            value={state.defaultModel}
            options={modelOptions}
            onValueChange={(value) =>
              apply({ defaultModel: value, defaultEffort: "" })
            }
            ariaLabel="Default model"
            disabled={off || models.isPending}
          />
        </SettingRow>

        <SettingRow
          label="Default effort"
          description="How much thinking the model spends per answer."
        >
          <SettingsOptionSelect
            value={
              effortOptions.some(
                (option) => option.value === state.defaultEffort,
              )
                ? state.defaultEffort
                : ""
            }
            options={effortOptions}
            onValueChange={(value) => apply({ defaultEffort: value })}
            ariaLabel="Default effort"
            disabled={off || effortOptions.length <= 1}
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
