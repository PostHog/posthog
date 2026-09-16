import { useServiceOptional } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Checkbox, Switch } from "@posthog/quill";
import {
  BACKGROUND_AGENT_LOGS_FLAG,
  ONBOARDING_TEST_TOOLS_FLAG,
} from "@posthog/shared";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import {
  SettingsCard,
  SettingsCardRow,
} from "@posthog/ui/features/settings/components/SettingsCard";
import {
  DEV_MODE_CLIENT,
  type DevModeClient,
} from "@posthog/ui/features/settings/devModeClient";
import { closeSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSetupStore } from "@posthog/ui/features/setup/setupStore";
import { useTourStore } from "@posthog/ui/features/tour/tourStore";
import { clearApplicationStorage } from "@posthog/ui/utils/clearStorage";
import { useQuery } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";
import { OnboardingTestTools } from "./OnboardingTestTools";
import { SettingsBackup } from "./SettingsBackup";

export function AdvancedSettings() {
  const showDebugLogsToggle =
    useFeatureFlag(BACKGROUND_AGENT_LOGS_FLAG) || import.meta.env.DEV;
  const debugLogsCloudRuns = useSettingsStore((s) => s.debugLogsCloudRuns);
  const setDebugLogsCloudRuns = useSettingsStore(
    (s) => s.setDebugLogsCloudRuns,
  );
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
  const showOnboardingTools = useFeatureFlag(ONBOARDING_TEST_TOOLS_FLAG);

  return (
    <div className="flex flex-col gap-7">
      <SettingsBackup />
      <SettingsCard>
        <SettingsCardRow
          label="Always create pull requests for cloud runs"
          description="Cloud runs push their changes and open a draft pull request when they finish, without waiting for you to ask"
        >
          <Switch
            checked={autoPublishCloudRuns}
            onCheckedChange={setAutoPublishCloudRuns}
            size="sm"
          />
        </SettingsCardRow>
        <SettingsCardRow
          label="Compress command output"
          description="Route eligible shell commands through rtk so their verbose output is compressed before it reaches the model, reducing token usage; Local covers local and worktree sessions"
        >
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-4">
              <label
                htmlFor="rtk-local"
                className="flex items-center gap-1 text-[12px]"
              >
                <Checkbox
                  id="rtk-local"
                  checked={rtkEnabledLocal}
                  onCheckedChange={(checked) =>
                    setRtkEnabledLocal(checked === true)
                  }
                />
                Local
              </label>
              <label
                htmlFor="rtk-cloud"
                className="flex items-center gap-1 text-[12px]"
              >
                <Checkbox
                  id="rtk-cloud"
                  checked={rtkEnabledCloud}
                  onCheckedChange={(checked) =>
                    setRtkEnabledCloud(checked === true)
                  }
                />
                Cloud
              </label>
            </div>
            {rtkEnabledLocal && rtkStatus?.available === false && (
              <span className="text-(--orange-11) text-[12px]">
                rtk binary not found. Local sessions run uncompressed until it
                is installed
              </span>
            )}
          </div>
        </SettingsCardRow>
        {showOnboardingTools && (
          <SettingsCardRow
            label="Reset onboarding and tours"
            description="Re-run the onboarding tutorial and product tours on next app restart"
          >
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                closeSettings();
                useOnboardingStore.getState().resetOnboarding();
                useSetupStore.getState().resetSetup();
                useTourStore.getState().resetTours();
              }}
            >
              Reset
            </Button>
          </SettingsCardRow>
        )}
        <SettingsCardRow
          label="Clear application storage"
          description="This will remove all locally stored application data"
        >
          <Button
            variant="destructive-outline"
            size="sm"
            onClick={clearApplicationStorage}
          >
            Clear all data
          </Button>
        </SettingsCardRow>
        {showDebugLogsToggle && (
          <SettingsCardRow
            label="Debug logs for cloud runs"
            description="Show debug-level console output in the conversation view for cloud-executed runs"
          >
            <Switch
              checked={debugLogsCloudRuns}
              onCheckedChange={setDebugLogsCloudRuns}
              size="sm"
            />
          </SettingsCardRow>
        )}
        {devModeClient && <DevModeRow client={devModeClient} />}
      </SettingsCard>
      {showOnboardingTools && <OnboardingTestTools />}
    </div>
  );
}

function DevModeRow({ client }: { client: DevModeClient }) {
  const devMode = useSyncExternalStore(
    client.onDevModeChanged,
    client.getDevMode,
  );

  return (
    <SettingsCardRow
      label="Developer mode"
      description="Show the dev toolbar with live CPU, memory, IPC timings and render tracking"
    >
      <Switch
        checked={devMode}
        onCheckedChange={(checked) => {
          void client.setDevMode(checked);
        }}
        size="sm"
      />
    </SettingsCardRow>
  );
}
