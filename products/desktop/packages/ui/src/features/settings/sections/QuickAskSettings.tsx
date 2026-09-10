import { isValidConfigValue } from "@posthog/core/task-detail/configOptions";
import { useServiceOptional } from "@posthog/di/react";
import { Switch } from "@posthog/quill";
import type { Adapter } from "@posthog/shared";
import { isSupportedReasoningEffort } from "@posthog/shared";
import { SpaceSelect } from "@posthog/ui/features/canvas/components/SpaceSelect";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import {
  QUICK_ASK_SETTINGS_CLIENT,
  type QuickAskSettingsClient,
  type QuickAskSettingsPatch,
  type QuickAskState,
} from "@posthog/ui/features/quick-ask/identifiers";
import { ReasoningLevelSelector } from "@posthog/ui/features/sessions/components/ReasoningLevelSelector";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { QuickAskShortcutSetting } from "@posthog/ui/features/settings/sections/QuickAskShortcutSetting";
import { usePreviewConfig } from "@posthog/ui/features/task-detail/hooks/usePreviewConfig";
import { Text } from "@radix-ui/themes";
import { useCallback, useEffect, useRef, useState } from "react";

/** The new-task model pill, wired to the persisted quick-ask defaults. */
function AgentDefaults({
  state,
  apply,
  disabled,
}: {
  state: QuickAskState;
  apply: (patch: QuickAskSettingsPatch) => void;
  disabled: boolean;
}) {
  const adapter: Adapter =
    state.defaultAdapter === "codex" ? "codex" : "claude";
  const { modelOption, thoughtOption, isLoading, setConfigOption } =
    usePreviewConfig(adapter);

  const seeded = useRef(false);
  useEffect(() => {
    if (seeded.current || isLoading) return;
    seeded.current = true;
    if (
      state.defaultModel &&
      modelOption &&
      isValidConfigValue(modelOption, state.defaultModel)
    ) {
      setConfigOption(modelOption.id, state.defaultModel);
    }
    if (
      state.defaultEffort &&
      thoughtOption &&
      isValidConfigValue(thoughtOption, state.defaultEffort)
    ) {
      setConfigOption(thoughtOption.id, state.defaultEffort);
    }
  }, [
    isLoading,
    modelOption,
    thoughtOption,
    setConfigOption,
    state.defaultModel,
    state.defaultEffort,
  ]);

  const handleModelChange = useCallback(
    (value: string) => {
      if (!modelOption) return;
      setConfigOption(modelOption.id, value);
      const effort =
        state.defaultEffort &&
        isSupportedReasoningEffort(adapter, value, state.defaultEffort)
          ? state.defaultEffort
          : "";
      apply({ defaultModel: value, defaultEffort: effort });
    },
    [modelOption, setConfigOption, adapter, state.defaultEffort, apply],
  );

  const handleThoughtChange = useCallback(
    (value: string) => {
      if (!thoughtOption) return;
      setConfigOption(thoughtOption.id, value);
      apply({ defaultEffort: value });
    },
    [thoughtOption, setConfigOption, apply],
  );

  const handleConfigOptionChange = useCallback(
    (configId: string, value: string) => {
      if (modelOption && configId === modelOption.id) {
        handleModelChange(value);
        return;
      }
      if (thoughtOption && configId === thoughtOption.id) {
        handleThoughtChange(value);
      }
    },
    [modelOption, thoughtOption, handleModelChange, handleThoughtChange],
  );

  return (
    <ReasoningLevelSelector
      thoughtOption={thoughtOption}
      modelOption={modelOption}
      adapter={adapter}
      onChange={handleThoughtChange}
      onModelChange={handleModelChange}
      onAdapterChange={(next) => {
        seeded.current = true;
        apply({
          defaultAdapter: next === "claude" ? "" : next,
          defaultModel: "",
          defaultEffort: "",
        });
      }}
      onConfigOptionChange={handleConfigOptionChange}
      disabled={disabled}
      isLoading={isLoading}
    />
  );
}

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
    <SettingsCard>
      <SettingsCardRow
        label="Enable quick ask"
        description="The floating panel and its global shortcut; turning this off frees the shortcut"
      >
        <Switch
          size="sm"
          checked={state.active}
          onCheckedChange={(checked) => apply({ active: checked })}
          aria-label="Enable quick ask"
        />
      </SettingsCardRow>

      <div
        className={
          off
            ? "pointer-events-none divide-y divide-border opacity-50"
            : "divide-y divide-border"
        }
      >
        <QuickAskShortcutSetting disabled={off} />

        <SettingsCardRow
          label="Default space"
          description="New quick-ask threads file into this space"
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
        </SettingsCardRow>

        <SettingsCardRow
          label="Default repositories"
          description={
            state.defaultRepositories.length === 0 &&
            spaceRepositories.length > 0
              ? `None of your own; the space brings ${spaceRepositories.join(", ")}.`
              : "Cloned into the sandbox for every new thread; leave empty for data-only answers, or to use the space's repositories"
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
        </SettingsCardRow>

        <SettingsCardRow
          label="Agent"
          description="The harness, model, and effort quick-ask answers run with"
        >
          <AgentDefaults state={state} apply={apply} disabled={off} />
        </SettingsCardRow>
      </div>
    </SettingsCard>
  );
}
