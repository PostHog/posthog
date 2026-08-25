import { CaretDown, Play, Plus, Trash } from "@phosphor-icons/react";
import { useServiceOptional } from "@posthog/di/react";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
} from "@posthog/platform/notifications";
import { type ISpeech, SPEECH_SERVICE } from "@posthog/platform/speech";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Input,
  Select,
  SelectContent,
  SelectGroup,
  SelectGroupLabel,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
  Slider,
  Switch,
  ToggleGroup,
  ToggleGroupItem,
} from "@posthog/quill";
import { ANALYTICS_EVENTS, SPOKEN_NARRATION_FLAG } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { NotificationBus } from "@posthog/ui/features/notifications/notifications";
import { NotificationDeliveryCard } from "@posthog/ui/features/settings/components/NotificationDeliveryCard";
import {
  SettingsCard,
  SettingsCardRow,
  SettingsSection,
} from "@posthog/ui/features/settings/components/SettingsCard";
import { SettingsSelect } from "@posthog/ui/features/settings/components/SettingsSelect";
import { AddCustomSoundDialog } from "@posthog/ui/features/settings/sections/AddCustomSoundDialog";
import { TipsSection } from "@posthog/ui/features/settings/sections/TipsSettings";
import {
  type CompletionSound,
  type CustomSound,
  NOTIFICATION_DEFAULTS,
  type SpokenFocusMode,
  useSettingsStore,
} from "@posthog/ui/features/settings/settingsStore";
import {
  type ISpeechKeyStore,
  SPEECH_KEY_STORE,
} from "@posthog/ui/features/settings/speechKeyStore";
import { useTasks } from "@posthog/ui/features/tasks/useTasks";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useHostCapabilities } from "@posthog/ui/shell/useHostCapabilities";
import { formatDurationSeconds } from "@posthog/ui/utils/customSound";
import { playCompletionSound } from "@posthog/ui/utils/sounds";
import { useCallback, useEffect, useState } from "react";

const BUILT_IN_SOUND_OPTIONS: { value: CompletionSound; label: string }[] = [
  { value: "guitar", label: "Guitar solo" },
  { value: "danilo", label: "I'm ready" },
  { value: "revi", label: "Cute noise" },
  { value: "meep", label: "Meep" },
  { value: "meep-smol", label: "Meep (smol)" },
  { value: "bubbles", label: "Bubbles" },
  { value: "drop", label: "Drop" },
  { value: "knock", label: "Knock" },
  { value: "ring", label: "Ring" },
  { value: "shoot", label: "Shoot" },
  { value: "slide", label: "Slide" },
  { value: "switch", label: "Switch" },
  { value: "wilhelm", label: "Wilhelm scream" },
  { value: "icq", label: "ICQ" },
  { value: "msn", label: "MSN Messenger" },
];

export function NotificationsSettings() {
  const {
    desktopNotifications,
    dockBadgeNotifications,
    dockBounceNotifications,
    toastNotifications,
    completionSound,
    completionVolume,
    scaleSoundWithTaskLength,
    customSounds,
    setDesktopNotifications,
    setDockBadgeNotifications,
    setDockBounceNotifications,
    setToastNotifications,
    setCompletionSound,
    setCompletionVolume,
    setScaleSoundWithTaskLength,
    removeCustomSound,
    renameCustomSound,
  } = useSettingsStore();

  const [addSoundOpen, setAddSoundOpen] = useState(false);

  // Optional so non-desktop hosts (web) that don't bind these simply disable the
  // native test actions instead of throwing.
  const bus = useServiceOptional<NotificationBus>(NotificationBus);
  const notifications = useServiceOptional<INotifications>(
    NOTIFICATIONS_SERVICE,
  );
  // Dock badge/bounce are macOS desktop-dock features.
  const { localWorkspaces } = useHostCapabilities();

  // Spoken narration is behind a flag for a staged rollout; always on in dev.
  const spokenNarrationEnabled = useFeatureFlag(
    SPOKEN_NARRATION_FLAG,
    import.meta.env.DEV,
  );

  // The most recent task, used to demo a real deep-link notification.
  const { data: tasks } = useTasks();
  const deepLinkTask = tasks?.[0];

  // Sync the toggle off if the user denied notification permission at the OS
  // level (otherwise it claims to be on but the OS silently drops everything).
  useEffect(() => {
    if (window.Notification?.permission === "denied" && desktopNotifications) {
      setDesktopNotifications(false);
    }
  }, [desktopNotifications, setDesktopNotifications]);

  const notificationsDenied = window.Notification?.permission === "denied";

  const handleDesktopNotificationsChange = useCallback(
    async (checked: boolean) => {
      if (checked) {
        const permission = await window.Notification?.requestPermission?.();
        if (permission !== "granted") {
          toast.info("Notifications are blocked", {
            description:
              "Allow notifications for PostHog in your system settings.",
          });
          return;
        }
      }
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "desktop_notifications",
        new_value: checked,
        old_value: desktopNotifications,
      });
      setDesktopNotifications(checked);
    },
    [desktopNotifications, setDesktopNotifications],
  );

  const handleToastNotificationsChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "toast_notifications",
        new_value: checked,
        old_value: toastNotifications,
      });
      setToastNotifications(checked);
    },
    [toastNotifications, setToastNotifications],
  );

  const handleCompletionSoundChange = useCallback(
    (value: CompletionSound) => {
      // Don't leak generated custom-sound ids into analytics.
      const analyticsValue = value.startsWith("custom:") ? "custom" : value;
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "completion_sound",
        new_value: analyticsValue,
        old_value: completionSound.startsWith("custom:")
          ? "custom"
          : completionSound,
      });
      setCompletionSound(value);
    },
    [completionSound, setCompletionSound],
  );

  const handleScaleSoundChange = useCallback(
    (checked: boolean) => {
      track(ANALYTICS_EVENTS.SETTING_CHANGED, {
        setting_name: "scale_sound_with_task_length",
        new_value: checked,
        old_value: scaleSoundWithTaskLength,
      });
      setScaleSoundWithTaskLength(checked);
    },
    [scaleSoundWithTaskLength, setScaleSoundWithTaskLength],
  );

  const resetToDefaults = useCallback(() => {
    setDesktopNotifications(NOTIFICATION_DEFAULTS.desktopNotifications);
    setDockBadgeNotifications(NOTIFICATION_DEFAULTS.dockBadgeNotifications);
    setDockBounceNotifications(NOTIFICATION_DEFAULTS.dockBounceNotifications);
    setToastNotifications(NOTIFICATION_DEFAULTS.toastNotifications);
    setCompletionSound(NOTIFICATION_DEFAULTS.completionSound);
    setCompletionVolume(NOTIFICATION_DEFAULTS.completionVolume);
    setScaleSoundWithTaskLength(NOTIFICATION_DEFAULTS.scaleSoundWithTaskLength);
    toast.success("Notification settings reset to defaults");
  }, [
    setDesktopNotifications,
    setDockBadgeNotifications,
    setDockBounceNotifications,
    setToastNotifications,
    setCompletionSound,
    setCompletionVolume,
    setScaleSoundWithTaskLength,
  ]);

  const soundItems = [
    { value: "none", label: "None" },
    { value: "random-all", label: "Random (all)" },
    ...(customSounds.length > 0
      ? [{ value: "random-custom", label: "Random (custom)" }]
      : []),
    ...BUILT_IN_SOUND_OPTIONS,
    ...customSounds.map((sound) => ({
      value: `custom:${sound.id}`,
      label: sound.name,
    })),
  ];

  return (
    <div className="flex flex-col gap-7">
      {notificationsDenied && (
        <div className="rounded-(--radius-3) border border-(--amber-6) bg-(--amber-2) px-3.5 py-2.5 text-[12.5px] text-amber-11">
          Notifications are blocked in your system settings. Allow them for
          PostHog to receive alerts.
        </div>
      )}

      <SettingsSection
        label="Alerts"
        description="How agents get your attention when they finish or need you."
        action={
          <Button
            type="button"
            variant="link-muted"
            size="sm"
            onClick={resetToDefaults}
          >
            Reset to defaults
          </Button>
        }
      >
        <div className="grid grid-cols-2 gap-2">
          <NotificationDeliveryCard
            title="System notifications"
            caption="When the app is in the background"
            illustration="push"
            checked={desktopNotifications}
            onCheckedChange={(checked) =>
              void handleDesktopNotificationsChange(checked)
            }
            disabled={notificationsDenied}
          />
          <NotificationDeliveryCard
            title="In-app toasts"
            caption="While you're elsewhere in the app"
            illustration="toast"
            checked={toastNotifications}
            onCheckedChange={handleToastNotificationsChange}
          />
          {localWorkspaces && (
            <>
              <NotificationDeliveryCard
                title="Dock badge"
                caption="Unread dot on the app icon"
                illustration="dock-badge"
                checked={dockBadgeNotifications}
                onCheckedChange={setDockBadgeNotifications}
              />
              <NotificationDeliveryCard
                title="Dock bounce"
                caption="Bounce the app icon once"
                illustration="dock-bounce"
                checked={dockBounceNotifications}
                onCheckedChange={setDockBounceNotifications}
              />
            </>
          )}
        </div>
      </SettingsSection>

      <SettingsSection label="Sound">
        <SettingsCard>
          <SettingsCardRow
            label="Completion sound"
            description="Plays when an agent finishes or needs your input"
          >
            <div className="flex items-center gap-1.5">
              <Select
                value={completionSound}
                onValueChange={(value: string | null) => {
                  if (value)
                    handleCompletionSoundChange(value as CompletionSound);
                }}
                items={soundItems}
              >
                <SelectTrigger
                  size="sm"
                  aria-label="Completion sound"
                  className="w-[150px]"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent align="end" side="bottom" sideOffset={6}>
                  <SelectItem value="none">None</SelectItem>
                  <SelectItem value="random-all">Random (all)</SelectItem>
                  {customSounds.length > 0 && (
                    <SelectItem value="random-custom">
                      Random (custom)
                    </SelectItem>
                  )}
                  <SelectSeparator />
                  {BUILT_IN_SOUND_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                  {customSounds.length > 0 && (
                    <>
                      <SelectSeparator />
                      <SelectGroup>
                        <SelectGroupLabel>Custom</SelectGroupLabel>
                        {customSounds.map((sound) => (
                          <SelectItem
                            key={sound.id}
                            value={`custom:${sound.id}`}
                          >
                            {sound.name}
                          </SelectItem>
                        ))}
                      </SelectGroup>
                    </>
                  )}
                </SelectContent>
              </Select>
              {completionSound !== "none" && (
                <Tooltip content="Preview">
                  <Button
                    type="button"
                    variant="outline"
                    size="icon-sm"
                    aria-label="Preview sound"
                    onClick={() =>
                      playCompletionSound(
                        completionSound,
                        completionVolume,
                        customSounds,
                      )
                    }
                  >
                    <Play weight="fill" size={12} />
                  </Button>
                </Tooltip>
              )}
              <Tooltip content="Record or import your own sound">
                <Button
                  type="button"
                  variant="outline"
                  size="icon-sm"
                  aria-label="Add a custom sound"
                  onClick={() => setAddSoundOpen(true)}
                >
                  <Plus size={12} />
                </Button>
              </Tooltip>
            </div>
          </SettingsCardRow>

          {customSounds.length > 0 && (
            <SettingsCardRow label="Custom sounds" stacked>
              <div className="flex w-full flex-col gap-1.5">
                {customSounds.map((sound) => (
                  <CustomSoundRow
                    key={sound.id}
                    sound={sound}
                    volume={completionVolume}
                    onRename={renameCustomSound}
                    onRemove={removeCustomSound}
                  />
                ))}
              </div>
            </SettingsCardRow>
          )}

          {completionSound !== "none" && (
            <>
              <SettingsCardRow label="Volume">
                <div className="flex items-center gap-3">
                  <Slider
                    aria-label="Sound volume"
                    value={[completionVolume]}
                    onValueChange={(next: number | readonly number[]) => {
                      const raw = Array.isArray(next) ? next[0] : next;
                      if (typeof raw === "number") setCompletionVolume(raw);
                    }}
                    min={0}
                    max={100}
                    step={1}
                    className="w-[120px]"
                  />
                  <span className="w-8 text-right text-[12px] text-gray-10 tabular-nums">
                    {completionVolume}%
                  </span>
                </div>
              </SettingsCardRow>

              <SettingsCardRow
                label="Match speed to task length"
                description="Quick tasks play the sound faster, long ones slower"
              >
                <Switch
                  size="sm"
                  checked={scaleSoundWithTaskLength}
                  onCheckedChange={handleScaleSoundChange}
                />
              </SettingsCardRow>
            </>
          )}
        </SettingsCard>
      </SettingsSection>

      <AddCustomSoundDialog
        open={addSoundOpen}
        onOpenChange={setAddSoundOpen}
      />

      {spokenNarrationEnabled && <VoiceSection />}

      <TipsSection />

      <TestSection
        bus={bus}
        notifications={notifications}
        deepLinkTask={deepLinkTask}
        localWorkspaces={localWorkspaces}
      />
    </div>
  );
}

type SpeakAboutKey = "needs_input" | "completion" | "progress";

// Voice narration: the agent speaks a short line when it needs the user or
// finishes. The master toggle reveals the sub-controls. The ElevenLabs key is
// written to encrypted host storage via an injected capability (never kept in
// packages/ui or the persisted blob).
function VoiceSection() {
  const {
    spokenNotifications,
    spokenNotifyNeedsInput,
    spokenNotifyCompletion,
    spokenNotifyProgress,
    spokenFocusMode,
    elevenLabsVoiceId,
    elevenLabsKeyConfigured,
    setSpokenNotifications,
    setSpokenNotifyNeedsInput,
    setSpokenNotifyCompletion,
    setSpokenNotifyProgress,
    setSpokenFocusMode,
    setElevenLabsVoiceId,
    setElevenLabsKeyConfigured,
  } = useSettingsStore();

  const keyStore = useServiceOptional<ISpeechKeyStore>(SPEECH_KEY_STORE);
  const speech = useServiceOptional<ISpeech>(SPEECH_SERVICE);
  const [keyDraft, setKeyDraft] = useState("");
  const [savingKey, setSavingKey] = useState(false);

  const speakAbout: SpeakAboutKey[] = [
    ...(spokenNotifyNeedsInput ? (["needs_input"] as const) : []),
    ...(spokenNotifyCompletion ? (["completion"] as const) : []),
    ...(spokenNotifyProgress ? (["progress"] as const) : []),
  ];

  const handleSpeakAboutChange = useCallback(
    (next: string[]) => {
      setSpokenNotifyNeedsInput(next.includes("needs_input"));
      setSpokenNotifyCompletion(next.includes("completion"));
      setSpokenNotifyProgress(next.includes("progress"));
    },
    [
      setSpokenNotifyNeedsInput,
      setSpokenNotifyCompletion,
      setSpokenNotifyProgress,
    ],
  );

  const saveKey = useCallback(async () => {
    if (!keyStore || !keyDraft.trim()) return;
    setSavingKey(true);
    try {
      await keyStore.save(keyDraft.trim());
      setElevenLabsKeyConfigured(true);
      setKeyDraft("");
      toast.success("ElevenLabs key saved");
    } catch {
      toast.error("Couldn't save the key");
    } finally {
      setSavingKey(false);
    }
  }, [keyStore, keyDraft, setElevenLabsKeyConfigured]);

  const clearKey = useCallback(async () => {
    if (!keyStore) return;
    try {
      await keyStore.clear();
      setElevenLabsKeyConfigured(false);
      toast.success("ElevenLabs key removed");
    } catch {
      toast.error("Couldn't remove the key");
    }
  }, [keyStore, setElevenLabsKeyConfigured]);

  const testVoice = useCallback(() => {
    void speech?.speak("PostHog task 'demo' — [excited] this is my voice!", {
      voiceId: elevenLabsVoiceId || undefined,
    });
  }, [speech, elevenLabsVoiceId]);

  return (
    <SettingsSection
      label="Voice"
      description="The agent says a short line out loud, so you catch it across parallel tasks without watching the screen."
    >
      <SettingsCard>
        <SettingsCardRow
          label="Spoken narration"
          description="Lines are serialized so agents never talk over each other"
        >
          <Switch
            size="sm"
            checked={spokenNotifications}
            onCheckedChange={setSpokenNotifications}
          />
        </SettingsCardRow>

        {spokenNotifications && (
          <>
            <SettingsCardRow
              label="Speak about"
              description="Needing you is always spoken, even for the task on screen"
            >
              <ToggleGroup
                multiple
                value={speakAbout}
                onValueChange={handleSpeakAboutChange}
                aria-label="Speak about"
                className="gap-1"
              >
                <ToggleGroupItem
                  value="needs_input"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2.5 text-[12px] text-gray-11 data-[pressed]:border-(--accent-9) data-[pressed]:bg-(--accent-3) data-[pressed]:text-(--accent-11)"
                >
                  Needs you
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="completion"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2.5 text-[12px] text-gray-11 data-[pressed]:border-(--accent-9) data-[pressed]:bg-(--accent-3) data-[pressed]:text-(--accent-11)"
                >
                  Task finished
                </ToggleGroupItem>
                <ToggleGroupItem
                  value="progress"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2.5 text-[12px] text-gray-11 data-[pressed]:border-(--accent-9) data-[pressed]:bg-(--accent-3) data-[pressed]:text-(--accent-11)"
                >
                  Progress
                </ToggleGroupItem>
              </ToggleGroup>
            </SettingsCardRow>

            <SettingsCardRow label="When to speak">
              <SettingsSelect
                ariaLabel="When to speak"
                value={spokenFocusMode}
                options={[
                  {
                    value: "unviewed_task",
                    label: "Quiet for the task I'm viewing",
                  },
                  {
                    value: "app_unfocused",
                    label: "Only when app is in background",
                  },
                  { value: "always", label: "Always" },
                ]}
                onChange={(value) => {
                  if (value) setSpokenFocusMode(value as SpokenFocusMode);
                }}
                triggerClassName="w-[220px]"
              />
            </SettingsCardRow>
          </>
        )}

        {(spokenNotifications || elevenLabsKeyConfigured) && (
          <SettingsCardRow
            label="ElevenLabs voice"
            description={
              elevenLabsKeyConfigured
                ? "Key saved. The expressive Eleven v3 voice is on."
                : "Optional. Add an API key for an expressive voice; otherwise your system voice is used."
            }
          >
            {elevenLabsKeyConfigured ? (
              <div className="flex items-center gap-1.5">
                <Input
                  className="h-7 w-[140px] text-[12px]"
                  placeholder="Default voice"
                  aria-label="ElevenLabs voice id"
                  value={elevenLabsVoiceId}
                  onChange={(e) => setElevenLabsVoiceId(e.currentTarget.value)}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={testVoice}
                  disabled={!speech}
                >
                  <Play weight="fill" size={11} /> Test
                </Button>
                <Button
                  type="button"
                  variant="link-muted"
                  size="sm"
                  onClick={clearKey}
                  disabled={!keyStore}
                >
                  Remove key
                </Button>
              </div>
            ) : (
              <div className="flex items-center gap-1.5">
                <Input
                  type="password"
                  placeholder="xi-…"
                  aria-label="ElevenLabs API key"
                  className="h-7 w-[140px] text-[12px]"
                  value={keyDraft}
                  onChange={(e) => setKeyDraft(e.currentTarget.value)}
                  disabled={!keyStore}
                />
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void saveKey()}
                  disabled={!keyStore || !keyDraft.trim() || savingKey}
                >
                  Save
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={testVoice}
                  disabled={!speech}
                >
                  <Play weight="fill" size={11} /> Test
                </Button>
              </div>
            )}
          </SettingsCardRow>
        )}
      </SettingsCard>
    </SettingsSection>
  );
}

// A single installed custom sound: inline-rename field, preview, and delete.
function CustomSoundRow({
  sound,
  volume,
  onRename,
  onRemove,
}: {
  sound: CustomSound;
  volume: number;
  onRename: (id: string, name: string) => void;
  onRemove: (id: string) => void;
}) {
  // Uncontrolled so the committed name (a prop) is the single source of truth —
  // no draft copy in state to drift out of sync. `key` remounts the field with
  // the new default whenever the stored name changes. On an empty/unchanged
  // blur we restore the displayed value rather than commit it.
  const commitName = (input: HTMLInputElement) => {
    const trimmed = input.value.trim();
    if (trimmed && trimmed !== sound.name) {
      onRename(sound.id, trimmed);
    } else {
      input.value = sound.name;
    }
  };

  return (
    <div className="flex items-center gap-1.5">
      <Input
        key={sound.name}
        className="h-7 flex-1 text-[12px]"
        defaultValue={sound.name}
        maxLength={60}
        aria-label={`Rename ${sound.name}`}
        onBlur={(event) => commitName(event.currentTarget)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      <span className="text-[11px] text-gray-9 tabular-nums">
        {formatDurationSeconds(sound.durationMs)}
      </span>
      <Tooltip content={`Play ${sound.name}`}>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label={`Play ${sound.name}`}
          onClick={() =>
            playCompletionSound(`custom:${sound.id}`, volume, [sound])
          }
        >
          <Play weight="fill" size={11} />
        </Button>
      </Tooltip>
      <Button
        type="button"
        variant="link-muted"
        size="icon-sm"
        aria-label={`Remove ${sound.name}`}
        onClick={() => onRemove(sound.id)}
      >
        <Trash size={13} />
      </Button>
    </div>
  );
}

// Fires each delivery channel directly (bypassing the focus-aware routing,
// since you're focused on Settings) so each tier can be verified in isolation.
function TestSection({
  bus,
  notifications,
  deepLinkTask,
  localWorkspaces,
}: {
  bus: NotificationBus | null;
  notifications: INotifications | null;
  deepLinkTask: Task | undefined;
  localWorkspaces: boolean;
}) {
  const nativeUnavailable = !notifications;

  const testToast = () =>
    bus?.notify({
      body: "Test notification",
      toast: {
        level: "success",
        description: "This is what an in-app toast looks like.",
      },
    });

  // A toast carrying a target renders a "View" action that deep-links — the
  // in-app counterpart of clicking a native notification.
  const testToastDeepLink = () => {
    if (!bus || !deepLinkTask) return;
    bus.notify({
      body: `"${deepLinkTask.title}"`,
      target: { kind: "task", taskId: deepLinkTask.id },
      toast: {
        level: "success",
        description: "Click “View task” to deep-link to it.",
      },
    });
  };

  const testNative = () =>
    notifications?.notify({
      title: "PostHog",
      body: "This is a native OS notification.",
      silent: false,
    });

  const testNativeDeepLink = () => {
    if (!notifications || !deepLinkTask) return;
    notifications.notify({
      title: "PostHog",
      body: `Click to open "${deepLinkTask.title}"`,
      silent: false,
      target: { kind: "task", taskId: deepLinkTask.id },
    });
  };

  return (
    <SettingsSection label="Test">
      <SettingsCard>
        <SettingsCardRow
          label="Send a test alert"
          description={
            nativeUnavailable
              ? "System notifications aren't available on this host"
              : "Fire a channel directly to check it works end to end"
          }
        >
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button type="button" variant="outline" size="sm">
                  Send test
                  <CaretDown size={10} weight="bold" />
                </Button>
              }
            />
            <DropdownMenuContent
              align="end"
              side="bottom"
              sideOffset={6}
              className="w-max"
            >
              <DropdownMenuItem onClick={testToast} disabled={!bus}>
                In-app toast
              </DropdownMenuItem>
              {localWorkspaces && (
                <DropdownMenuItem
                  onClick={testToastDeepLink}
                  disabled={!bus || !deepLinkTask}
                >
                  Toast that opens the latest task
                </DropdownMenuItem>
              )}
              <DropdownMenuItem
                onClick={testNative}
                disabled={nativeUnavailable}
              >
                System notification
              </DropdownMenuItem>
              {localWorkspaces && (
                <>
                  <DropdownMenuItem
                    onClick={testNativeDeepLink}
                    disabled={nativeUnavailable || !deepLinkTask}
                  >
                    Notification that opens the latest task
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => notifications?.showUnreadIndicator()}
                    disabled={nativeUnavailable}
                  >
                    Dock badge
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onClick={() => notifications?.requestAttention()}
                    disabled={nativeUnavailable}
                  >
                    Dock bounce
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </SettingsCardRow>
      </SettingsCard>
    </SettingsSection>
  );
}
