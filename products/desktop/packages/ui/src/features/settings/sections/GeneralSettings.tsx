import { ArrowSquareOut } from "@phosphor-icons/react";
import { buildPostHogUrl } from "@posthog/core/settings/posthogUrl";
import { useHostTRPC } from "@posthog/host-router/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import {
  COLLAPSE_MODE_OPTIONS,
  type CollapseMode,
} from "@posthog/ui/features/sessions/components/new-thread/conversationThreadConfig";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
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
import { Button, Flex, Link, Select, Switch, Text } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useCallback, useEffect } from "react";

export function GeneralSettings() {
  const hostTRPC = useHostTRPC();
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  // Appearance state
  const theme = useThemeStore((state) => state.theme);
  const setTheme = useThemeStore((state) => state.setTheme);
  // Power state
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

  // Chat state
  const {
    autoConvertLongText,
    defaultInitialTaskMode,
    defaultMessagingMode,
    defaultReasoningEffort,
    diffOpenMode,
    sendMessagesWith,
    conversationCollapseMode,
    hedgehogMode,
    slotMachineMode,
    brainrotMode,
    setAutoConvertLongText,
    setDefaultInitialTaskMode,
    setDefaultMessagingMode,
    setDefaultReasoningEffort,
    setDiffOpenMode,
    setSendMessagesWith,
    setConversationCollapseMode,
    setHedgehogMode,
    setSlotMachineMode,
    setBrainrotMode,
  } = useSettingsStore();

  // Appearance handlers
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

  // Chat handlers
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

  const handleConversationCollapseModeChange = useCallback(
    (value: CollapseMode) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "conversation_collapse_mode",
        new_value: value,
        old_value: conversationCollapseMode,
      });
      setConversationCollapseMode(value);
    },
    [conversationCollapseMode, setConversationCollapseMode],
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

  const handleHedgehogModeChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "hedgehog_mode",
        new_value: checked,
        old_value: hedgehogMode,
      });
      setHedgehogMode(checked);
    },
    [hedgehogMode, setHedgehogMode],
  );

  const handleSlotMachineModeChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "slot_machine_mode",
        new_value: checked,
        old_value: slotMachineMode,
      });
      setSlotMachineMode(checked);
    },
    [slotMachineMode, setSlotMachineMode],
  );

  const handleBrainrotModeChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "brainrot_mode",
        new_value: checked,
        old_value: brainrotMode,
      });
      setBrainrotMode(checked);
    },
    [brainrotMode, setBrainrotMode],
  );

  const accountUrl = buildPostHogUrl("/settings/user", cloudRegion);

  return (
    <Flex direction="column">
      {isAuthenticated && (
        <SettingRow
          label="Manage Account"
          description="Manage your account and billing on PostHog"
        >
          <Button
            size="1"
            variant="outline"
            disabled={!accountUrl}
            onClick={() => {
              if (accountUrl) window.open(accountUrl, "_blank");
            }}
          >
            Manage
            <ArrowSquareOut size={12} />
          </Button>
        </SettingRow>
      )}

      {/* Appearance */}
      <Text className="mb-2 pt-4 font-medium text-sm">Appearance</Text>

      <SettingRow
        label="Theme"
        description="Choose light, dark, or follow your system preference"
      >
        <Select.Root
          value={theme}
          onValueChange={(v) => handleThemeChange(v as ThemePreference)}
          size="1"
        >
          <Select.Trigger className="min-w-[100px]" />
          <Select.Content>
            <Select.Item value="light">Light</Select.Item>
            <Select.Item value="dark">Dark</Select.Item>
            <Select.Item value="system">System</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      {/* Input */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Input
      </Text>

      <SettingRow
        label="Initial task mode"
        description="Choose whether new tasks always start in Plan mode or remember your last-used mode"
      >
        <Select.Root
          value={defaultInitialTaskMode}
          onValueChange={(value) =>
            handleDefaultInitialTaskModeChange(value as DefaultInitialTaskMode)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[100px]" />
          <Select.Content>
            <Select.Item value="plan">Plan</Select.Item>
            <Select.Item value="last_used">Last used</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      <SettingRow
        label="Default messaging mode"
        description="Mode new sessions start in. Steer applies messages mid-turn. Queue holds them until the turn ends."
      >
        <Select.Root
          value={defaultMessagingMode}
          onValueChange={(value) =>
            handleDefaultMessagingModeChange(value as DefaultMessagingMode)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[100px]" />
          <Select.Content>
            <Select.Item value="queue">Queue</Select.Item>
            <Select.Item value="steer">Steer</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      <SettingRow
        label="Default effort level"
        description="Choose the default reasoning effort for new tasks, or remember your last-used level"
      >
        <Select.Root
          value={defaultReasoningEffort}
          onValueChange={(value) =>
            handleDefaultReasoningEffortChange(value as DefaultReasoningEffort)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[100px]" />
          <Select.Content>
            <Select.Item value="last_used">Last used</Select.Item>
            <Select.Item value="low">Low</Select.Item>
            <Select.Item value="medium">Medium</Select.Item>
            <Select.Item value="high">High</Select.Item>
            <Select.Item value="xhigh">Extra High</Select.Item>
            <Select.Item value="max">Max</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      <SettingRow
        label="Send messages with"
        description="Choose which key combination sends messages. Use Shift+Enter for new lines"
      >
        <Select.Root
          value={sendMessagesWith}
          onValueChange={(value) =>
            handleSendMessagesWithChange(value as SendMessagesWith)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[100px]" />
          <Select.Content>
            <Select.Item value="enter">Enter</Select.Item>
            <Select.Item value="cmd+enter">⌘ Enter</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      <SettingRow
        label="Auto-convert long text"
        description="Automatically convert pasted text over this length into an attachment"
      >
        <Select.Root
          value={autoConvertLongText}
          onValueChange={(value) =>
            handleAutoConvertLongTextChange(value as AutoConvertLongText)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[120px]" />
          <Select.Content>
            <Select.Item value="off">Off</Select.Item>
            <Select.Item value="1000">1,000 chars</Select.Item>
            <Select.Item value="2500">2,500 chars</Select.Item>
            <Select.Item value="5000">5,000 chars</Select.Item>
            <Select.Item value="10000">10,000 chars</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      {/* Editor */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Editor
      </Text>

      <SettingRow
        label="Open diffs in"
        description="Choose how file diffs open when clicking a changed file"
        noBorder
      >
        <Select.Root
          value={diffOpenMode}
          onValueChange={(value) =>
            handleDiffOpenModeChange(value as DiffOpenMode)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[140px]" />
          <Select.Content>
            <Select.Item value="auto">Auto</Select.Item>
            <Select.Item value="split">Split pane</Select.Item>
            <Select.Item value="same-pane">Same pane</Select.Item>
            <Select.Item value="last-active-pane">Last active pane</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      {/* Conversation */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Conversation
      </Text>

      <SettingRow
        label="Collapse tool calls"
        description="Group each turn's tool calls into a collapsible summary. Partial keeps the active turn expanded and folds completed turns."
        noBorder
      >
        <Select.Root
          value={conversationCollapseMode}
          onValueChange={(value) =>
            handleConversationCollapseModeChange(value as CollapseMode)
          }
          size="1"
        >
          <Select.Trigger className="min-w-[140px]" />
          <Select.Content>
            {COLLAPSE_MODE_OPTIONS.map((opt) => (
              <Select.Item key={opt.value} value={opt.value}>
                {opt.label}
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Root>
      </SettingRow>

      {/* Power */}
      {localWorkspaces && (
        <>
          <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
            Power
          </Text>

          <SettingRow
            label="Keep awake while agents work"
            description={
              hasBuiltInBattery
                ? "Prevent your computer from going to sleep on its own while the agent is running a task. Closing the lid will still put it to sleep."
                : "Prevent your computer from going to sleep on its own while the agent is running a task"
            }
            noBorder
          >
            <Switch
              checked={preventSleepWhileRunning}
              onCheckedChange={handlePreventSleepChange}
              size="1"
            />
          </SettingRow>
        </>
      )}

      {/* Fun */}
      <Text className="mb-2 block border-gray-6 border-t pt-4 font-medium text-sm">
        Fun
      </Text>

      <SettingRow label="Hedgehog mode" description={<HedgehogDescription />}>
        <Switch
          checked={hedgehogMode}
          onCheckedChange={handleHedgehogModeChange}
          size="1"
        />
      </SettingRow>

      <SettingRow
        label="Slot machine mode 🎰"
        description="Show a pull-able slot machine lever while a task is running. Every run is a gamble. Pull the handle and watch the reels spin."
      >
        <Switch
          checked={slotMachineMode}
          onCheckedChange={handleSlotMachineModeChange}
          size="1"
        />
      </SettingRow>

      <SettingRow
        label="Brainrot mode ⚡"
        description="Add a Brainrot option to empty command center cells that fills them with a looping background video."
        noBorder
      >
        <Switch
          checked={brainrotMode}
          onCheckedChange={handleBrainrotModeChange}
          size="1"
        />
      </SettingRow>
    </Flex>
  );
}

function HedgehogDescription() {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  const customizeUrl = projectId
    ? buildPostHogUrl(
        `/project/${projectId}/settings/user-customization`,
        cloudRegion,
      )
    : null;

  return (
    <Flex direction="column" gap="1">
      <Text color="gray" className="text-[13px]">
        Release a hedgehog buddy to walk around your screen. It might take a few
        seconds to appear.
      </Text>
      {customizeUrl && (
        <Text color="gray" className="text-[13px]">
          <Link href={customizeUrl} target="_blank">
            Customize your hedgehog
          </Link>
        </Text>
      )}
    </Flex>
  );
}
