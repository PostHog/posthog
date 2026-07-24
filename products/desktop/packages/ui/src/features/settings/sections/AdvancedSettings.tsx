import { useServiceOptional } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useLoopsPromoStore } from "@posthog/ui/features/loops/loopsPromoStore";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import {
  DEV_MODE_CLIENT,
  type DevModeClient,
} from "@posthog/ui/features/settings/devModeClient";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSetupStore } from "@posthog/ui/features/setup/setupStore";
import { useTourStore } from "@posthog/ui/features/tour/tourStore";
import { clearApplicationStorage } from "@posthog/ui/utils/clearStorage";
import { Button, Checkbox, Flex, Switch, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

export function AdvancedSettings() {
  const showDebugLogsToggle =
    useFeatureFlag("posthog-code-background-agent-logs") || import.meta.env.DEV;
  const debugLogsCloudRuns = useSettingsStore((s) => s.debugLogsCloudRuns);
  const setDebugLogsCloudRuns = useSettingsStore(
    (s) => s.setDebugLogsCloudRuns,
  );
  const useNewChatThread = useSettingsStore((s) => s.useNewChatThread);
  const setUseNewChatThread = useSettingsStore((s) => s.setUseNewChatThread);
  const autoPublishCloudRuns = useSettingsStore((s) => s.autoPublishCloudRuns);
  const setAutoPublishCloudRuns = useSettingsStore(
    (s) => s.setAutoPublishCloudRuns,
  );
  const rtkEnabledLocal = useSettingsStore((s) => s.rtkEnabledLocal);
  const setRtkEnabledLocal = useSettingsStore((s) => s.setRtkEnabledLocal);
  const rtkEnabledCloud = useSettingsStore((s) => s.rtkEnabledCloud);
  const setRtkEnabledCloud = useSettingsStore((s) => s.setRtkEnabledCloud);
  const hostTRPC = useHostTRPC();
  const { data: rtkStatus } = useQuery(hostTRPC.agent.rtkStatus.queryOptions());
  const devModeClient = useServiceOptional<DevModeClient>(DEV_MODE_CLIENT);

  return (
    <Flex direction="column">
      <SettingRow
        label="Always create pull requests for cloud runs"
        description="Cloud runs push their changes and open a draft pull request when they finish, without waiting for you to ask"
      >
        <Switch
          checked={autoPublishCloudRuns}
          onCheckedChange={setAutoPublishCloudRuns}
          size="1"
        />
      </SettingRow>
      <SettingRow
        label="Compress command output"
        description="Route eligible shell commands through rtk so their verbose output is compressed before it reaches the model, reducing token usage. Local covers local and worktree sessions"
      >
        <Flex direction="column" gap="1" align="end">
          <Flex gap="4" align="center">
            <Text as="label" size="1">
              <Flex gap="1" align="center">
                <Checkbox
                  checked={rtkEnabledLocal}
                  onCheckedChange={(checked) =>
                    setRtkEnabledLocal(checked === true)
                  }
                  size="1"
                />
                Local
              </Flex>
            </Text>
            <Text as="label" size="1">
              <Flex gap="1" align="center">
                <Checkbox
                  checked={rtkEnabledCloud}
                  onCheckedChange={(checked) =>
                    setRtkEnabledCloud(checked === true)
                  }
                  size="1"
                />
                Cloud
              </Flex>
            </Text>
          </Flex>
          {rtkEnabledLocal && rtkStatus?.available === false && (
            <Text size="1" color="orange">
              rtk binary not found — local sessions run uncompressed until it is
              installed
            </Text>
          )}
        </Flex>
      </SettingRow>
      <SettingRow
        label="Reset onboarding and tours"
        description="Re-run the onboarding tutorial and product tours on next app restart"
      >
        <Button
          variant="soft"
          size="1"
          onClick={() => {
            closeSettings();
            useOnboardingStore.getState().resetOnboarding();
            useSetupStore.getState().resetSetup();
            useTourStore.getState().resetTours();
            useLoopsPromoStore.getState().reset();
          }}
        >
          Reset
        </Button>
      </SettingRow>
      <SettingRow
        label="Clear application storage"
        description="This will remove all locally stored application data"
      >
        <Button
          variant="soft"
          color="red"
          size="1"
          onClick={clearApplicationStorage}
        >
          Clear all data
        </Button>
      </SettingRow>
      {showDebugLogsToggle && (
        <SettingRow
          label="Debug logs for cloud runs"
          description="Show debug-level console output in the conversation view for cloud-executed runs"
        >
          <Switch
            checked={debugLogsCloudRuns}
            onCheckedChange={setDebugLogsCloudRuns}
            size="1"
          />
        </SettingRow>
      )}
      <SettingRow
        label="Use new chat thread (experimental)"
        description="Render conversations with the new ChatX (quill) primitives instead of the virtualized thread"
        noBorder={!devModeClient}
      >
        <Switch
          checked={useNewChatThread}
          onCheckedChange={setUseNewChatThread}
          size="1"
        />
      </SettingRow>
      {devModeClient && <DevModeRow client={devModeClient} />}
    </Flex>
  );
}

function DevModeRow({ client }: { client: DevModeClient }) {
  const devMode = useSyncExternalStore(
    client.onDevModeChanged,
    client.getDevMode,
  );

  return (
    <SettingRow
      label="Developer mode"
      description="Show the dev toolbar with live CPU, memory, IPC timings and render tracking"
      noBorder
    >
      <Switch
        checked={devMode}
        onCheckedChange={(checked) => {
          void client.setDevMode(checked);
        }}
        size="1"
      />
    </SettingRow>
  );
}
