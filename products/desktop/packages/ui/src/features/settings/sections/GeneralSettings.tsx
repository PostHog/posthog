import { ArrowSquareOut } from "@phosphor-icons/react";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { useServiceOptional } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Switch } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import {
  EFFORT_LEVEL_DOCS_URLS,
  EFFORT_LEVEL_LABELS,
  EFFORT_LEVELS,
} from "@posthog/shared/domain-types";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  MISSION_CONTROL_CLIENT,
  type MissionControlClient,
} from "@posthog/ui/features/mission-control/identifiers";
import {
  ReasoningLevelDropdown,
  type ReasoningLevelOption,
} from "@posthog/ui/features/sessions/components/ReasoningLevelDropdown";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { ThemePicker } from "@posthog/ui/features/settings/components/ThemePicker";
import { UpdatesSection } from "@posthog/ui/features/settings/sections/UpdatesSettings";
import {
  type AutoConvertLongText,
  type DefaultInitialTaskMode,
  type DefaultMessagingMode,
  type DefaultReasoningEffort,
  type DiffOpenMode,
  type SendMessagesWith,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import { track } from "@posthog/ui/shell/analytics";
import type { ThemePreference } from "@posthog/ui/shell/themeStore";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

const DEFAULT_EFFORT_OPTIONS: ReasoningLevelOption[] = [
  { value: "last_used", label: "Last used" },
  ...EFFORT_LEVELS.map((level) => ({
    value: level,
    label: EFFORT_LEVEL_LABELS[level],
    docsUrl: EFFORT_LEVEL_DOCS_URLS[level],
  })),
];

const MESSAGING_MODE_OPTIONS = [
  { value: "queue", label: "Queue" },
  { value: "steer", label: "Steer" },
];

export function GeneralSettings() {
  const hostTRPC = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);

  const { localWorkspaces } = useHostCapabilities();
  const { preventSleepWhileRunning, setPreventSleepWhileRunning } =
    useSettingsStore();
  const { data: serverPreventSleep } = useQuery(
    hostTRPC.sleep.getEnabled.queryOptions(undefined, {
      enabled: localWorkspaces,
    }),
  );
  const { data: hasBuiltInBattery } = useQuery(
    hostTRPC.sleep.hasBuiltInBattery.queryOptions(undefined, {
      enabled: localWorkspaces,
    }),
  );
  const preventSleepMutation = useMutation(
    hostTRPC.sleep.setEnabled.mutationOptions(),
  );

  useEffect(() => {
    if (serverPreventSleep !== undefined) {
      setPreventSleepWhileRunning(serverPreventSleep);
    }
  }, [serverPreventSleep, setPreventSleepWhileRunning]);

  const handlePreventSleepChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "prevent_sleep_while_running",
        new_value: checked,
        old_value: !checked,
      });
      setPreventSleepWhileRunning(checked);
      preventSleepMutation.mutate({ enabled: checked });
    },
    [setPreventSleepWhileRunning, preventSleepMutation],
  );

  // Mission Control overlay state. The client is bound on desktop only, so on
  // other hosts this resolves to null and the setting is hidden.
  const queryClient = useQueryClient();
  const missionControl = useServiceOptional<MissionControlClient>(
    MISSION_CONTROL_CLIENT,
  );
  const { data: missionControlSupported } = useQuery({
    queryKey: ["missionControlOverlay", "supported"],
    queryFn: () => missionControl?.isSupported() ?? false,
    enabled: missionControl != null,
  });
  const { data: missionControlEnabled } = useQuery({
    queryKey: ["missionControlOverlay", "enabled"],
    queryFn: () => missionControl?.getEnabled() ?? false,
    enabled: missionControl != null && missionControlSupported === true,
  });
  const missionControlMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      missionControl?.setEnabled(enabled) ?? Promise.resolve(),
  });

  const handleMissionControlOverlayChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "mission_control_overlay",
        new_value: checked,
        old_value: !checked,
      });
      queryClient.setQueryData(["missionControlOverlay", "enabled"], checked);
      missionControlMutation.mutate(checked);
    },
    [missionControlMutation, queryClient],
  );

  const {
    autoConvertLongText,
    defaultInitialTaskMode,
    defaultMessagingMode,
    defaultCloudMessagingMode,
    defaultReasoningEffort,
    diffOpenMode,
    sendMessagesWith,
    setAutoConvertLongText,
    setDefaultInitialTaskMode,
    setDefaultMessagingMode,
    setDefaultCloudMessagingMode,
    setDefaultReasoningEffort,
    setDiffOpenMode,
    setSendMessagesWith,
  } = useSettingsStore();

  const handleThemeChange = useCallback(
    (value: ThemePreference) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "theme",
        new_value: value,
        old_value: theme,
      });
      setTheme(value);
    },
    [theme, setTheme],
  );

  const handleAutoConvertLongTextChange = useCallback(
    (value: AutoConvertLongText) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "auto_convert_long_text",
        new_value: value,
        old_value: autoConvertLongText,
      });
      setAutoConvertLongText(value);
    },
    [autoConvertLongText, setAutoConvertLongText],
  );

  const handleDiffOpenModeChange = useCallback(
    (value: DiffOpenMode) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "diff_open_mode",
        new_value: value,
        old_value: diffOpenMode,
      });
      setDiffOpenMode(value);
    },
    [diffOpenMode, setDiffOpenMode],
  );

  const handleDefaultInitialTaskModeChange = useCallback(
    (value: DefaultInitialTaskMode) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "default_initial_task_mode",
        new_value: value,
        old_value: defaultInitialTaskMode,
      });
      setDefaultInitialTaskMode(value);
    },
    [defaultInitialTaskMode, setDefaultInitialTaskMode],
  );

  const handleDefaultMessagingModeChange = useCallback(
    (value: DefaultMessagingMode) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "default_messaging_mode",
        new_value: value,
        old_value: defaultMessagingMode,
      });
      setDefaultMessagingMode(value);
    },
    [defaultMessagingMode, setDefaultMessagingMode],
  );

  const handleDefaultCloudMessagingModeChange = useCallback(
    (value: DefaultMessagingMode) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "default_cloud_messaging_mode",
        new_value: value,
        old_value: defaultCloudMessagingMode,
      });
      setDefaultCloudMessagingMode(value);
    },
    [defaultCloudMessagingMode, setDefaultCloudMessagingMode],
  );

  const handleDefaultReasoningEffortChange = useCallback(
    (value: DefaultReasoningEffort) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "default_reasoning_effort",
        new_value: value,
        old_value: defaultReasoningEffort,
      });
      setDefaultReasoningEffort(value);
    },
    [defaultReasoningEffort, setDefaultReasoningEffort],
  );

  const handleSendMessagesWithChange = useCallback(
    (value: SendMessagesWith) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "send_messages_with",
        new_value: value,
        old_value: sendMessagesWith,
      });
      setSendMessagesWith(value);
    },
    [sendMessagesWith, setSendMessagesWith],
  );

  const accountUrl = buildPostHogUrl("/settings/user", cloudRegion);

  return (
    <div className="flex flex-col gap-7">
      {isAuthenticated && (
        <SettingsCard>
          <SettingsCardRow
            label="PostHog account"
            description="Account and billing details are managed on PostHog"
          >
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={!accountUrl}
              onClick={() => {
                if (accountUrl) window.open(accountUrl, "_blank");
              }}
            >
              Manage
              <ArrowSquareOut size={12} />
            </Button>
          </SettingsCardRow>
        </SettingsCard>
      )}

      <SettingsSection label="Appearance">
        <ThemePicker value={theme} onChange={handleThemeChange} />
        {missionControl != null && missionControlSupported === true && (
          <SettingsCard>
            <SettingsCardRow
              label="Mission Control overlay"
              description="Show the PostHog logo over the window in macOS Mission Control"
            >
              <Switch
                size="sm"
                checked={missionControlEnabled ?? false}
                onCheckedChange={handleMissionControlOverlayChange}
              />
            </SettingsCardRow>
          </SettingsCard>
        )}
      </SettingsSection>

      <SettingsSection
        label="New tasks"
        description="Defaults for every new task. You can change any of these per task in the composer."
      >
        <SettingsCard>
          <SettingsCardRow label="Start in">
            <SettingsSegmented
              ariaLabel="Initial task mode"
              value={defaultInitialTaskMode}
              options={[
                { value: "plan", label: "Plan" },
                { value: "last_used", label: "Last used" },
              ]}
              onValueChange={(value) =>
                handleDefaultInitialTaskModeChange(
                  value as DefaultInitialTaskMode,
                )
              }
            />
          </SettingsCardRow>

          <SettingsCardRow label="Effort">
            <ReasoningLevelDropdown
              value={defaultReasoningEffort}
              options={DEFAULT_EFFORT_OPTIONS}
              onChange={(value) =>
                handleDefaultReasoningEffortChange(
                  value as DefaultReasoningEffort,
                )
              }
              side="bottom"
              triggerVariant="outline"
              triggerClassName="min-w-[120px] justify-between"
            />
          </SettingsCardRow>

          <SettingsCardRow
            label="Messaging"
            description="Queue holds messages until the turn ends. Steer applies them mid-turn."
          >
            <div className="flex items-center gap-5">
              <div className="flex flex-col items-start gap-1">
                <span className="text-[10px] text-gray-9 uppercase tracking-wide">
                  Local
                </span>
                <SettingsSegmented
                  ariaLabel="Local messaging mode"
                  value={defaultMessagingMode}
                  options={MESSAGING_MODE_OPTIONS}
                  onValueChange={(value) =>
                    handleDefaultMessagingModeChange(
                      value as DefaultMessagingMode,
                    )
                  }
                />
              </div>
              <div className="flex flex-col items-start gap-1">
                <span className="text-[10px] text-gray-9 uppercase tracking-wide">
                  Cloud
                </span>
                <SettingsSegmented
                  ariaLabel="Cloud messaging mode"
                  value={defaultCloudMessagingMode}
                  options={MESSAGING_MODE_OPTIONS}
                  onValueChange={(value) =>
                    handleDefaultCloudMessagingModeChange(
                      value as DefaultMessagingMode,
                    )
                  }
                />
              </div>
            </div>
          </SettingsCardRow>
        </SettingsCard>
      </SettingsSection>

      <SettingsSection label="Composer">
        <SettingsCard>
          <SettingsCardRow
            label="Send messages with"
            description={
              sendMessagesWith === "enter"
                ? "Shift+Enter inserts a new line"
                : undefined
            }
          >
            <SettingsSegmented
              ariaLabel="Send messages with"
              value={sendMessagesWith}
              options={[
                { value: "enter", label: "Enter" },
                { value: "cmd+enter", label: "⌘ Enter" },
              ]}
              onValueChange={(value) =>
                handleSendMessagesWithChange(value as SendMessagesWith)
              }
            />
          </SettingsCardRow>

          <SettingsCardRow
            label="Convert long pastes to attachments"
            description="Pasted text over this length becomes an attachment"
          >
            <SettingsSelect
              ariaLabel="Convert long pastes to attachments"
              value={autoConvertLongText}
              options={[
                { value: "off", label: "Off" },
                { value: "1000", label: "1,000 characters" },
                { value: "2500", label: "2,500 characters" },
                { value: "5000", label: "5,000 characters" },
                { value: "10000", label: "10,000 characters" },
              ]}
              onChange={(value) => {
                if (value)
                  handleAutoConvertLongTextChange(value as AutoConvertLongText);
              }}
              triggerClassName="w-[160px]"
            />
          </SettingsCardRow>
        </SettingsCard>
      </SettingsSection>

      <SettingsSection label="Editor">
        <SettingsCard>
          <SettingsCardRow label="Open diffs in">
            <SettingsSelect
              ariaLabel="Open diffs in"
              value={diffOpenMode}
              options={[
                { value: "auto", label: "Auto" },
                { value: "split", label: "Split pane" },
                { value: "same-pane", label: "Same pane" },
                { value: "last-active-pane", label: "Last active pane" },
              ]}
              onChange={(value) => {
                if (value) handleDiffOpenModeChange(value as DiffOpenMode);
              }}
              triggerClassName="w-[160px]"
            />
          </SettingsCardRow>

          {localWorkspaces && (
            <SettingsCardRow
              label="Keep awake while agents work"
              description={
                hasBuiltInBattery
                  ? "Stops your computer from sleeping on its own during a task. Closing the lid still puts it to sleep."
                  : "Stops your computer from sleeping on its own during a task"
              }
            >
              <Switch
                size="sm"
                checked={preventSleepWhileRunning}
                onCheckedChange={handlePreventSleepChange}
              />
            </SettingsCardRow>
          )}
        </SettingsCard>
      </SettingsSection>

      {localWorkspaces && <UpdatesSection />}
    </div>
  );
}
