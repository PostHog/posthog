import { Text } from "@components/text";
import { router } from "expo-router";
import { ArrowSquareOut, CaretRight, SpeakerHigh } from "phosphor-react-native";
import { useState } from "react";
import { Linking, Pressable, ScrollView, Switch, View } from "react-native";
import { useAuthStore, useProjectsQuery, useUserQuery } from "@/features/auth";
import { useDismissedReportsStore } from "@/features/inbox/stores/dismissedReportsStore";
import { usePushTokenStore } from "@/features/notifications/stores/pushTokenStore";
import {
  type CompletionSound,
  type DefaultReasoningEffort,
  type FontSizePreference,
  type InitialTaskMode,
  type ThemePreference,
  usePreferencesStore,
} from "@/features/preferences/stores/preferencesStore";
import { DebugInfoSection } from "@/features/settings/components/DebugInfoSection";
import { FloatingSettingsHeader } from "@/features/settings/components/FloatingSettingsHeader";
import { SettingsRow } from "@/features/settings/components/SettingsRow";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import { SelectSheet } from "@/features/tasks/composer/SelectSheet";
import {
  type MessagingMode,
  useMessagingModeStore,
} from "@/features/tasks/stores/messagingModeStore";
import { playCompletionSound } from "@/features/tasks/utils/sounds";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";

const THEME_OPTIONS = [
  { value: "system", label: "Match system" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
] as const;

const FONT_SIZE_OPTIONS: ReadonlyArray<{
  value: FontSizePreference;
  label: string;
}> = [
  { value: "small", label: "Small" },
  { value: "default", label: "Default" },
  { value: "large", label: "Large" },
  { value: "xlarge", label: "Extra Large" },
];

const SOUND_OPTIONS: ReadonlyArray<{ value: CompletionSound; label: string }> =
  [
    { value: "meep", label: "Meep" },
    { value: "meep-smol", label: "Meep (smol)" },
    { value: "knock", label: "Knock" },
    { value: "ring", label: "Ring" },
    { value: "shoot", label: "Shoot" },
    { value: "slide", label: "Slide" },
    { value: "drop", label: "Drop" },
    { value: "icq", label: "ICQ" },
  ];

const VOLUME_OPTIONS = [
  { value: "25", label: "Quiet (25%)" },
  { value: "50", label: "Normal (50%)" },
  { value: "75", label: "Loud (75%)" },
  { value: "100", label: "Max (100%)" },
] as const;

const TASK_MODE_OPTIONS = [
  {
    value: "plan",
    label: "Plan",
    description: "New tasks always start in Plan mode",
  },
  {
    value: "last_used",
    label: "Last used",
    description: "Remember the mode you picked last time",
  },
] as const;

const MESSAGING_MODE_OPTIONS: ReadonlyArray<{
  value: MessagingMode;
  label: string;
  description: string;
}> = [
  {
    value: "queue",
    label: "Queue",
    description: "Hold messages until the current turn finishes",
  },
  {
    value: "steer",
    label: "Steer",
    description: "Interrupt the current turn and send right away",
  },
];

const REASONING_EFFORT_OPTIONS: ReadonlyArray<{
  value: DefaultReasoningEffort;
  label: string;
  description?: string;
}> = [
  {
    value: "last_used",
    label: "Last used",
    description: "Remember the effort level you picked last time",
  },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
  { value: "xhigh", label: "Extra High" },
  { value: "max", label: "Max" },
];

function themeLabel(theme: ThemePreference): string {
  return THEME_OPTIONS.find((o) => o.value === theme)?.label ?? "Match system";
}

function fontSizeLabel(size: FontSizePreference): string {
  return FONT_SIZE_OPTIONS.find((o) => o.value === size)?.label ?? "Default";
}

function soundLabel(sound: CompletionSound): string {
  return SOUND_OPTIONS.find((o) => o.value === sound)?.label ?? "Meep";
}

function volumeLabel(volume: number): string {
  if (volume >= 100) return "Max";
  if (volume >= 75) return "Loud";
  if (volume >= 50) return "Normal";
  return "Quiet";
}

function taskModeLabel(mode: InitialTaskMode): string {
  return TASK_MODE_OPTIONS.find((o) => o.value === mode)?.label ?? "Plan";
}

function messagingModeLabel(mode: MessagingMode): string {
  return MESSAGING_MODE_OPTIONS.find((o) => o.value === mode)?.label ?? "Queue";
}

function reasoningEffortLabel(effort: DefaultReasoningEffort): string {
  return (
    REASONING_EFFORT_OPTIONS.find((o) => o.value === effort)?.label ??
    "Last used"
  );
}

export default function SettingsScreen() {
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();

  const {
    logout,
    cloudRegion,
    projectId,
    scopedTeams,
    setProjectId,
    getCloudUrlFromRegion,
  } = useAuthStore();
  const { data: userData } = useUserQuery();
  const { data: projects } = useProjectsQuery();

  const pingsEnabled = usePreferencesStore((s) => s.pingsEnabled);
  const setPingsEnabled = usePreferencesStore((s) => s.setPingsEnabled);
  const pushNotificationsEnabled = usePreferencesStore(
    (s) => s.pushNotificationsEnabled,
  );
  const setPushNotificationsEnabled = usePreferencesStore(
    (s) => s.setPushNotificationsEnabled,
  );
  const theme = usePreferencesStore((s) => s.theme);
  const setTheme = usePreferencesStore((s) => s.setTheme);
  const fontSize = usePreferencesStore((s) => s.fontSize);
  const setFontSize = usePreferencesStore((s) => s.setFontSize);
  const completionSound = usePreferencesStore((s) => s.completionSound);
  const setCompletionSound = usePreferencesStore((s) => s.setCompletionSound);
  const completionVolume = usePreferencesStore((s) => s.completionVolume);
  const setCompletionVolume = usePreferencesStore((s) => s.setCompletionVolume);
  const scaleSoundWithTaskLength = usePreferencesStore(
    (s) => s.scaleSoundWithTaskLength,
  );
  const setScaleSoundWithTaskLength = usePreferencesStore(
    (s) => s.setScaleSoundWithTaskLength,
  );
  const defaultInitialTaskMode = usePreferencesStore(
    (s) => s.defaultInitialTaskMode,
  );
  const setDefaultInitialTaskMode = usePreferencesStore(
    (s) => s.setDefaultInitialTaskMode,
  );
  const defaultReasoningEffort = usePreferencesStore(
    (s) => s.defaultReasoningEffort,
  );
  const setDefaultReasoningEffort = usePreferencesStore(
    (s) => s.setDefaultReasoningEffort,
  );
  const autoPublishCloudRuns = usePreferencesStore(
    (s) => s.autoPublishCloudRuns,
  );
  const setAutoPublishCloudRuns = usePreferencesStore(
    (s) => s.setAutoPublishCloudRuns,
  );
  const rtkEnabledCloud = usePreferencesStore((s) => s.rtkEnabledCloud);
  const setRtkEnabledCloud = usePreferencesStore((s) => s.setRtkEnabledCloud);
  const defaultMessagingMode = useMessagingModeStore((s) => s.defaultMode);
  const setDefaultMessagingMode = useMessagingModeStore(
    (s) => s.setDefaultMode,
  );
  const decidedCount = useDismissedReportsStore(
    (s) => s.dismissedIds.length + s.acceptedIds.length,
  );
  const clearDismissed = useDismissedReportsStore((s) => s.clearDismissed);

  const [themeSheetOpen, setThemeSheetOpen] = useState(false);
  const [fontSizeSheetOpen, setFontSizeSheetOpen] = useState(false);
  const [soundSheetOpen, setSoundSheetOpen] = useState(false);
  const [volumeSheetOpen, setVolumeSheetOpen] = useState(false);
  const [taskModeSheetOpen, setTaskModeSheetOpen] = useState(false);
  const [reasoningEffortSheetOpen, setReasoningEffortSheetOpen] =
    useState(false);
  const [messagingModeSheetOpen, setMessagingModeSheetOpen] = useState(false);
  const [projectSheetOpen, setProjectSheetOpen] = useState(false);

  // The selected project's name. Prefer the names fetched for the scoped teams
  // (matched on the active projectId), falling back to the backend's current
  // team name, then a bare ID. The picker is only useful with >1 project.
  const selectedProjectName =
    projects?.find((p) => p.id === projectId)?.name ||
    userData?.team?.name ||
    (projectId != null ? `Project ${projectId}` : "—");
  const canSwitchProject = scopedTeams.length > 1;

  const handleTogglePushNotifications = (enabled: boolean) => {
    setPushNotificationsEnabled(enabled);
    if (enabled) {
      usePushTokenStore
        .getState()
        .registerAndUpload()
        .catch((error) => {
          logger.warn("Push token registration failed", error);
        });
    } else {
      usePushTokenStore
        .getState()
        .clear()
        .catch((error) => {
          logger.warn("Push token clear failed", error);
        });
    }
  };

  const handleLogout = async () => {
    await logout();
    router.replace("/auth");
  };

  const handleOpenWebSettings = () => {
    if (!cloudRegion) return;
    const baseUrl = getCloudUrlFromRegion(cloudRegion);
    Linking.openURL(`${baseUrl}/settings`).catch(() => {});
  };

  const handleTestSound = () => {
    playCompletionSound().catch(() => {});
  };

  // Top padding leaves room for the floating header (insets.top + ~52). Bottom
  // padding clears the home indicator and gives breathing room past the last
  // row so it never hides behind it.
  const contentPaddingTop = insets.top + 60;
  const contentPaddingBottom = bottom("default");

  return (
    <View className="flex-1 bg-background">
      <FloatingSettingsHeader />

      <ScrollView
        className="flex-1"
        contentContainerStyle={{
          paddingTop: contentPaddingTop,
          paddingBottom: contentPaddingBottom,
          paddingHorizontal: 16,
        }}
        showsVerticalScrollIndicator={false}
      >
        {/* Appearance */}
        <SettingsSection title="Appearance">
          <SettingsRow
            label="Theme"
            description="Choose light, dark, or follow your system preference"
            onPress={() => setThemeSheetOpen(true)}
            rightSlot={
              <>
                <Text className="text-[14px] text-gray-11">
                  {themeLabel(theme)}
                </Text>
                <CaretRight size={14} color={themeColors.gray[10]} />
              </>
            }
          />
          <SettingsRow
            label="Font size"
            description="Scale text size across the app"
            onPress={() => setFontSizeSheetOpen(true)}
            showDivider={false}
            rightSlot={
              <>
                <Text className="text-[14px] text-gray-11">
                  {fontSizeLabel(fontSize)}
                </Text>
                <CaretRight size={14} color={themeColors.gray[10]} />
              </>
            }
          />
        </SettingsSection>

        {/* Notifications */}
        <SettingsSection title="Notifications">
          <SettingsRow
            label="Push notifications"
            description="Get notified when a task finishes or needs your input"
            rightSlot={
              <Switch
                value={pushNotificationsEnabled}
                onValueChange={handleTogglePushNotifications}
              />
            }
          />
          <SettingsRow
            label="Enable pings"
            description="Play a sound when a task completes"
            showDivider={false}
            rightSlot={
              <Switch value={pingsEnabled} onValueChange={setPingsEnabled} />
            }
          />
        </SettingsSection>

        {/* Sound */}
        {pingsEnabled ? (
          <SettingsSection title="Sound">
            <SettingsRow
              label="Completion sound"
              description="Pick the sound that plays when a task completes"
              onPress={() => setSoundSheetOpen(true)}
              rightSlot={
                <>
                  <Pressable
                    onPress={handleTestSound}
                    hitSlop={8}
                    className="rounded-md bg-gray-3 px-2 py-1 active:opacity-60"
                  >
                    <SpeakerHigh size={14} color={themeColors.gray[12]} />
                  </Pressable>
                  <Text className="text-[14px] text-gray-11">
                    {soundLabel(completionSound)}
                  </Text>
                  <CaretRight size={14} color={themeColors.gray[10]} />
                </>
              }
            />
            <SettingsRow
              label="Sound volume"
              description="How loud the completion sound plays"
              onPress={() => setVolumeSheetOpen(true)}
              rightSlot={
                <>
                  <Text className="text-[14px] text-gray-11">
                    {volumeLabel(completionVolume)} ({completionVolume}%)
                  </Text>
                  <CaretRight size={14} color={themeColors.gray[10]} />
                </>
              }
            />
            <SettingsRow
              label="Scale sound speed with task length"
              description="Play the sound faster for quick tasks and slower for long ones"
              showDivider={false}
              rightSlot={
                <Switch
                  value={scaleSoundWithTaskLength}
                  onValueChange={setScaleSoundWithTaskLength}
                />
              }
            />
          </SettingsSection>
        ) : null}

        {/* Input */}
        <SettingsSection title="Input">
          <SettingsRow
            label="Initial task mode"
            description="What mode new tasks start in"
            onPress={() => setTaskModeSheetOpen(true)}
            rightSlot={
              <>
                <Text className="text-[14px] text-gray-11">
                  {taskModeLabel(defaultInitialTaskMode)}
                </Text>
                <CaretRight size={14} color={themeColors.gray[10]} />
              </>
            }
          />
          <SettingsRow
            label="Default effort level"
            description="Reasoning effort to pre-fill on new tasks"
            onPress={() => setReasoningEffortSheetOpen(true)}
            rightSlot={
              <>
                <Text className="text-[14px] text-gray-11">
                  {reasoningEffortLabel(defaultReasoningEffort)}
                </Text>
                <CaretRight size={14} color={themeColors.gray[10]} />
              </>
            }
          />
          <SettingsRow
            label="Messaging mode"
            description="What happens when you send while a turn is running"
            onPress={() => setMessagingModeSheetOpen(true)}
            rightSlot={
              <>
                <Text className="text-[14px] text-gray-11">
                  {messagingModeLabel(defaultMessagingMode)}
                </Text>
                <CaretRight size={14} color={themeColors.gray[10]} />
              </>
            }
          />
          <SettingsRow
            label="Always create pull requests for cloud runs"
            description="Cloud runs push their changes and open a draft pull request when they finish, without waiting for you to ask"
            rightSlot={
              <Switch
                value={autoPublishCloudRuns}
                onValueChange={setAutoPublishCloudRuns}
              />
            }
          />
          <SettingsRow
            label="Compress command output"
            description="Route verbose shell command output through rtk so it is compressed before it reaches the model, reducing token usage"
            showDivider={false}
            rightSlot={
              <Switch
                value={rtkEnabledCloud}
                onValueChange={setRtkEnabledCloud}
              />
            }
          />
        </SettingsSection>

        {/* Integrations */}
        <SettingsSection title="Integrations">
          <SettingsRow
            label="MCP servers"
            description="Browse the marketplace, manage installed servers, approve tools"
            onPress={() => router.push("/mcp-servers")}
            showDivider={false}
            rightSlot={<CaretRight size={14} color={themeColors.gray[10]} />}
          />
        </SettingsSection>

        {/* Inbox */}
        <SettingsSection title="Inbox">
          <SettingsRow
            label="Reviewed reports"
            description={`${decidedCount} report${decidedCount === 1 ? "" : "s"} reviewed in tinder mode`}
            showDivider={false}
            rightSlot={
              <Pressable
                onPress={clearDismissed}
                disabled={decidedCount === 0}
                hitSlop={6}
                className={`rounded-md border px-3 py-1.5 ${decidedCount > 0 ? "border-gray-6 bg-gray-3 active:opacity-60" : "border-gray-4 opacity-40"}`}
              >
                <Text className="font-medium text-[13px] text-gray-12">
                  Clear
                </Text>
              </Pressable>
            }
          />
        </SettingsSection>

        {/* Organization */}
        <SettingsSection title="Organization">
          <SettingsRow
            label="Region"
            rightSlot={
              <Text className="font-medium text-[14px] text-gray-12">
                {cloudRegion?.toUpperCase() || "—"}
              </Text>
            }
          />
          <SettingsRow
            label="Display name"
            showDivider={false}
            rightSlot={
              <Text
                className="max-w-[180px] text-right font-medium text-[14px] text-gray-12"
                numberOfLines={1}
              >
                {userData?.organization?.name || "—"}
              </Text>
            }
          />
        </SettingsSection>

        {/* Project */}
        <SettingsSection title="Project">
          {canSwitchProject ? (
            <SettingsRow
              label="Active project"
              description="Tasks, inbox and automations use this project"
              onPress={() => setProjectSheetOpen(true)}
              showDivider={false}
              rightSlot={
                <>
                  <Text
                    className="max-w-[180px] text-right font-medium text-[14px] text-gray-12"
                    numberOfLines={1}
                  >
                    {selectedProjectName}
                  </Text>
                  <CaretRight size={14} color={themeColors.gray[10]} />
                </>
              }
            />
          ) : (
            <SettingsRow
              label="Display name"
              showDivider={false}
              rightSlot={
                <Text
                  className="max-w-[180px] text-right font-medium text-[14px] text-gray-12"
                  numberOfLines={1}
                >
                  {selectedProjectName}
                </Text>
              }
            />
          )}
        </SettingsSection>

        {/* Profile */}
        <SettingsSection title="Profile">
          <SettingsRow
            label="First name"
            rightSlot={
              <Text
                className="max-w-[180px] text-right font-medium text-[14px] text-gray-12"
                numberOfLines={1}
              >
                {userData?.first_name || "—"}
              </Text>
            }
          />
          <SettingsRow
            label="Last name"
            rightSlot={
              <Text
                className="max-w-[180px] text-right font-medium text-[14px] text-gray-12"
                numberOfLines={1}
              >
                {userData?.last_name || "—"}
              </Text>
            }
          />
          <SettingsRow
            label="Email"
            showDivider={false}
            rightSlot={
              <Text
                className="max-w-[220px] text-right font-medium text-[14px] text-gray-12"
                numberOfLines={1}
              >
                {userData?.email || "—"}
              </Text>
            }
          />
        </SettingsSection>

        {/* Account */}
        <SettingsSection title="Account">
          <SettingsRow
            label="All PostHog settings"
            description="Open your full settings on the PostHog website"
            onPress={handleOpenWebSettings}
            disabled={!cloudRegion}
            rightSlot={
              <ArrowSquareOut size={16} color={themeColors.gray[11]} />
            }
          />
          <SettingsRow
            label="Sign out"
            description="Sign out of this device"
            onPress={handleLogout}
            showDivider={false}
            rightSlot={
              <Text className="font-medium text-[14px] text-status-error">
                Sign out
              </Text>
            }
          />
        </SettingsSection>

        {/* Debug info — staff only */}
        {userData?.is_staff ? (
          <DebugInfoSection
            cloudRegion={cloudRegion}
            projectId={projectId}
            userId={userData.id}
            userUuid={userData.uuid}
          />
        ) : null}
      </ScrollView>

      <SelectSheet
        open={themeSheetOpen}
        title="Theme"
        value={theme}
        onChange={(value) => setTheme(value as ThemePreference)}
        onClose={() => setThemeSheetOpen(false)}
        options={THEME_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
        }))}
      />

      <SelectSheet
        open={fontSizeSheetOpen}
        title="Font size"
        value={fontSize}
        onChange={(value) => setFontSize(value as FontSizePreference)}
        onClose={() => setFontSizeSheetOpen(false)}
        options={FONT_SIZE_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
        }))}
      />

      <SelectSheet
        open={soundSheetOpen}
        title="Completion sound"
        value={completionSound}
        onChange={(value) => {
          const next = value as CompletionSound;
          setCompletionSound(next);
          playCompletionSound(next).catch(() => {});
        }}
        onClose={() => setSoundSheetOpen(false)}
        options={SOUND_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
        }))}
      />

      <SelectSheet
        open={volumeSheetOpen}
        title="Sound volume"
        value={String(completionVolume) as "25" | "50" | "75" | "100"}
        onChange={(value) => {
          const next = parseInt(value, 10);
          setCompletionVolume(next);
          playCompletionSound(undefined, next).catch(() => {});
        }}
        onClose={() => setVolumeSheetOpen(false)}
        options={VOLUME_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
        }))}
      />

      <SelectSheet
        open={taskModeSheetOpen}
        title="Initial task mode"
        value={defaultInitialTaskMode}
        onChange={(value) =>
          setDefaultInitialTaskMode(value as InitialTaskMode)
        }
        onClose={() => setTaskModeSheetOpen(false)}
        options={TASK_MODE_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
          description: option.description,
        }))}
      />

      <SelectSheet
        open={reasoningEffortSheetOpen}
        title="Default effort level"
        value={defaultReasoningEffort}
        onChange={(value) =>
          setDefaultReasoningEffort(value as DefaultReasoningEffort)
        }
        onClose={() => setReasoningEffortSheetOpen(false)}
        options={REASONING_EFFORT_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
          description: option.description,
        }))}
      />

      <SelectSheet
        open={messagingModeSheetOpen}
        title="Messaging mode"
        value={defaultMessagingMode}
        onChange={(value) => setDefaultMessagingMode(value as MessagingMode)}
        onClose={() => setMessagingModeSheetOpen(false)}
        options={MESSAGING_MODE_OPTIONS.map((option) => ({
          value: option.value,
          label: option.label,
          description: option.description,
        }))}
      />

      <SelectSheet
        open={projectSheetOpen}
        title="Active project"
        value={projectId != null ? String(projectId) : ""}
        onChange={(value) => setProjectId(Number(value))}
        onClose={() => setProjectSheetOpen(false)}
        options={scopedTeams.map((id) => ({
          value: String(id),
          label: projects?.find((p) => p.id === id)?.name || `Project ${id}`,
          description: String(id),
        }))}
      />
    </View>
  );
}
