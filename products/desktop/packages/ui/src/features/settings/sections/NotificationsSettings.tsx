import { Play, Plus, Trash } from "@phosphor-icons/react";
import { useServiceOptional } from "@posthog/di/react";
import {
  type INotifications,
  NOTIFICATIONS_SERVICE,
} from "@posthog/platform/notifications";
import { type ISpeech, SPEECH_SERVICE } from "@posthog/platform/speech";
import {
  ANALYTICS_EVENTS,
  PROJECT_BLUEBIRD_FLAG,
  SPOKEN_NARRATION_FLAG,
} from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { NotificationBus } from "@posthog/ui/features/notifications/notifications";
import { SettingRow } from "@posthog/ui/features/settings/SettingRow";
import { AddCustomSoundDialog } from "@posthog/ui/features/settings/sections/AddCustomSoundDialog";
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
import {
  Button,
  Flex,
  IconButton,
  Select,
  Slider,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useCallback, useEffect, useState } from "react";

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
  // native test buttons instead of throwing.
  const bus = useServiceOptional<NotificationBus>(NotificationBus);
  const notifications = useServiceOptional<INotifications>(
    NOTIFICATIONS_SERVICE,
  );
  // Dock badge/bounce are macOS desktop-dock features.
  const { localWorkspaces } = useHostCapabilities();

  // Canvases only exist behind the bluebird flag, so only mention them when on.
  const canvasEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );

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

  return (
    <Flex direction="column">
      {notificationsDenied && (
        <Text color="yellow" className="mb-2 text-[13px]">
          Notifications are blocked in your system settings. Enable
          notifications for PostHog to receive them.
        </Text>
      )}

      <Flex align="center" justify="between" className="mb-2 pt-2">
        <Text className="font-medium text-sm">Defaults</Text>
        <Button variant="soft" size="1" onClick={resetToDefaults}>
          Reset to defaults
        </Button>
      </Flex>

      <SettingRow
        label="Push notifications"
        description="Receive a native OS notification when the app is in the background and an agent finishes or needs your input"
      >
        <Switch
          checked={desktopNotifications}
          onCheckedChange={handleDesktopNotificationsChange}
          disabled={notificationsDenied}
          size="1"
        />
      </SettingRow>

      {localWorkspaces && (
        <>
          <SettingRow
            label="Dock badge"
            description="Display a badge on the dock icon when the agent finishes a task or needs your input"
          >
            <Switch
              checked={dockBadgeNotifications}
              onCheckedChange={setDockBadgeNotifications}
              size="1"
            />
          </SettingRow>

          <SettingRow
            label="Bounce dock icon"
            description="Bounce the dock icon when the agent finishes a task or needs your input"
          >
            <Switch
              checked={dockBounceNotifications}
              onCheckedChange={setDockBounceNotifications}
              size="1"
            />
          </SettingRow>
        </>
      )}

      <SettingRow
        label="In-app toasts"
        description="Show an in-app toast when the agent finishes a task or needs your input, and for other in-app confirmations. Error messages always show."
      >
        <Switch
          checked={toastNotifications}
          onCheckedChange={handleToastNotificationsChange}
          size="1"
        />
      </SettingRow>

      <SettingRow
        label="Sound effect"
        description="Play a sound when the agent finishes a task or needs your input"
        noBorder={completionSound === "none"}
      >
        <Flex align="center" gap="2">
          <Select.Root
            value={completionSound}
            onValueChange={(value) =>
              handleCompletionSoundChange(value as CompletionSound)
            }
            size="1"
          >
            <Select.Trigger className="min-w-[100px]" />
            <Select.Content>
              <Select.Item value="none">None</Select.Item>
              <Select.Item value="random-all">Random (all)</Select.Item>
              {customSounds.length > 0 && (
                <Select.Item value="random-custom">Random (custom)</Select.Item>
              )}
              <Select.Item value="guitar">Guitar solo</Select.Item>
              <Select.Item value="danilo">I'm ready</Select.Item>
              <Select.Item value="revi">Cute noise</Select.Item>
              <Select.Item value="meep">Meep</Select.Item>
              <Select.Item value="meep-smol">Meep (smol)</Select.Item>
              <Select.Item value="bubbles">Bubbles</Select.Item>
              <Select.Item value="drop">Drop</Select.Item>
              <Select.Item value="knock">Knock</Select.Item>
              <Select.Item value="ring">Ring</Select.Item>
              <Select.Item value="shoot">Shoot</Select.Item>
              <Select.Item value="slide">Slide</Select.Item>
              <Select.Item value="switch">Switch</Select.Item>
              <Select.Item value="wilhelm">Wilhelm scream</Select.Item>
              <Select.Item value="icq">ICQ</Select.Item>
              <Select.Item value="msn">MSN Messenger</Select.Item>
              {customSounds.length > 0 && (
                <Select.Group>
                  <Select.Label>Custom</Select.Label>
                  {customSounds.map((sound) => (
                    <Select.Item key={sound.id} value={`custom:${sound.id}`}>
                      {sound.name}
                    </Select.Item>
                  ))}
                </Select.Group>
              )}
            </Select.Content>
          </Select.Root>
          {completionSound !== "none" && (
            <Tooltip content="Test sound">
              <IconButton
                variant="soft"
                size="1"
                aria-label="Test sound"
                onClick={() =>
                  playCompletionSound(
                    completionSound,
                    completionVolume,
                    customSounds,
                  )
                }
              >
                <Play weight="fill" />
              </IconButton>
            </Tooltip>
          )}
        </Flex>
      </SettingRow>

      <SettingRow
        label="Custom sounds"
        description={
          customSounds.length > 0
            ? "Sounds you recorded or imported. Rename or remove them here."
            : "Record or import your own sound to play when an agent finishes a task or needs your input."
        }
      >
        <Flex direction="column" gap="2" className="w-full max-w-[260px]">
          {customSounds.map((sound) => (
            <CustomSoundRow
              key={sound.id}
              sound={sound}
              volume={completionVolume}
              onRename={renameCustomSound}
              onRemove={removeCustomSound}
            />
          ))}
          <Button
            variant="soft"
            size="1"
            className="self-start"
            onClick={() => setAddSoundOpen(true)}
          >
            <Plus /> Add
          </Button>
        </Flex>
      </SettingRow>

      <AddCustomSoundDialog
        open={addSoundOpen}
        onOpenChange={setAddSoundOpen}
      />

      {completionSound !== "none" && (
        <SettingRow label="Sound volume">
          <Flex align="center" gap="3">
            <Slider
              value={[completionVolume]}
              onValueChange={([value]) => setCompletionVolume(value)}
              min={0}
              max={100}
              step={1}
              size="1"
              className="w-[120px]"
            />
            <Text color="gray" className="text-[13px]">
              {completionVolume}%
            </Text>
          </Flex>
        </SettingRow>
      )}

      {completionSound !== "none" && (
        <SettingRow
          label="Scale sound speed with task length"
          description="Play the sound faster for quick tasks and slower for long ones"
          noBorder
        >
          <Switch
            checked={scaleSoundWithTaskLength}
            onCheckedChange={handleScaleSoundChange}
            size="1"
          />
        </SettingRow>
      )}

      {spokenNarrationEnabled && <SpokenNotificationsSection />}

      <NotificationTestHarness
        bus={bus}
        notifications={notifications}
        deepLinkTask={deepLinkTask}
        canvasEnabled={canvasEnabled}
      />
    </Flex>
  );
}

function SpeechSwitchRow({
  label,
  description,
  checked,
  onCheckedChange,
  disabled,
}: {
  label: string;
  description: string;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <SettingRow label={label} description={description}>
      <Switch
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        size="1"
      />
    </SettingRow>
  );
}

// Voice narration: the agent speaks a short line when it needs the user or
// finishes. The master toggle gates the whole feature; sub-controls disable
// when it's off. The ElevenLabs key is written to encrypted host storage via an
// injected capability (never kept in packages/ui or the persisted blob).
function SpokenNotificationsSection() {
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

  const disabled = !spokenNotifications;

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
    <>
      <Text className="mt-4 mb-1 block border-gray-6 border-t pt-4 font-medium text-sm">
        Spoken notifications
      </Text>
      <Text color="gray" className="mb-1 text-[13px]">
        Have the agent say a short line out loud when it needs you or finishes,
        so you hear it across parallel tasks without watching the screen. Lines
        are serialized so agents never talk over each other.
      </Text>

      <SpeechSwitchRow
        label="Enable spoken notifications"
        description="Let the agent speak up out loud when it decides it's worth interrupting you."
        checked={spokenNotifications}
        onCheckedChange={setSpokenNotifications}
      />

      <SpeechSwitchRow
        label="Speak when I'm needed"
        description="Blocked on a question, decision, or confirmation. Always spoken — even for the task you're viewing."
        checked={spokenNotifyNeedsInput}
        onCheckedChange={setSpokenNotifyNeedsInput}
        disabled={disabled}
      />

      <SpeechSwitchRow
        label="Speak when a task finishes"
        description="Announce completion so you can review and ship."
        checked={spokenNotifyCompletion}
        onCheckedChange={setSpokenNotifyCompletion}
        disabled={disabled}
      />

      <SpeechSwitchRow
        label="Speak on progress"
        description="Narrate meaningful new phases too. Off by default — can get chatty."
        checked={spokenNotifyProgress}
        onCheckedChange={setSpokenNotifyProgress}
        disabled={disabled}
      />

      <SettingRow
        label="When to speak"
        description="Choose how spoken lines behave relative to what's on screen. Needs-you lines always play."
      >
        <Select.Root
          value={spokenFocusMode}
          onValueChange={(v) => setSpokenFocusMode(v as SpokenFocusMode)}
          disabled={disabled}
          size="1"
        >
          <Select.Trigger className="min-w-[180px]" />
          <Select.Content>
            <Select.Item value="unviewed_task">
              Quiet for the task I'm viewing
            </Select.Item>
            <Select.Item value="app_unfocused">
              Only when app is in background
            </Select.Item>
            <Select.Item value="always">Always</Select.Item>
          </Select.Content>
        </Select.Root>
      </SettingRow>

      <SettingRow
        label="ElevenLabs API key"
        description={
          elevenLabsKeyConfigured
            ? "A key is saved — expressive Eleven v3 voice is on."
            : "Optional. Add a key for an expressive Eleven v3 voice; otherwise your system voice is used."
        }
      >
        {elevenLabsKeyConfigured ? (
          <Flex align="center" gap="2">
            <Text color="green" className="text-[13px]">
              Key saved
            </Text>
            <Button
              variant="soft"
              size="1"
              color="red"
              onClick={clearKey}
              disabled={!keyStore}
            >
              Remove
            </Button>
          </Flex>
        ) : (
          <Flex align="center" gap="2">
            <TextField.Root
              type="password"
              placeholder="xi-…"
              size="1"
              className="w-[180px]"
              value={keyDraft}
              onChange={(e) => setKeyDraft(e.currentTarget.value)}
              disabled={disabled || !keyStore}
            />
            <Button
              variant="soft"
              size="1"
              onClick={saveKey}
              disabled={disabled || !keyStore || !keyDraft.trim() || savingKey}
            >
              Save
            </Button>
          </Flex>
        )}
      </SettingRow>

      <SettingRow
        label="Voice"
        description="Optional ElevenLabs voice id. Leave blank for the default voice."
        noBorder
      >
        <Flex align="center" gap="2">
          <TextField.Root
            size="1"
            className="w-[180px]"
            placeholder="default"
            value={elevenLabsVoiceId}
            onChange={(e) => setElevenLabsVoiceId(e.currentTarget.value)}
            disabled={disabled}
          />
          <Button
            variant="soft"
            size="1"
            onClick={testVoice}
            disabled={disabled || !speech}
          >
            <Play weight="fill" /> Test
          </Button>
        </Flex>
      </SettingRow>
    </>
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
    <Flex align="center" gap="2">
      <TextField.Root
        key={sound.name}
        className="flex-1"
        size="1"
        defaultValue={sound.name}
        maxLength={60}
        onBlur={(event) => commitName(event.currentTarget)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
        }}
      />
      <Text color="gray" className="text-[12px] tabular-nums">
        {formatDurationSeconds(sound.durationMs)}
      </Text>
      <Tooltip content={`Play ${sound.name}`}>
        <IconButton
          variant="soft"
          size="1"
          aria-label={`Play ${sound.name}`}
          onClick={() =>
            playCompletionSound(`custom:${sound.id}`, volume, [sound])
          }
        >
          <Play weight="fill" />
        </IconButton>
      </Tooltip>
      <IconButton
        variant="ghost"
        color="gray"
        size="1"
        aria-label={`Remove ${sound.name}`}
        onClick={() => onRemove(sound.id)}
      >
        <Trash />
      </IconButton>
    </Flex>
  );
}

// Fires each delivery channel directly (bypassing the focus-aware routing, since
// you're focused on Settings) so each tier can be verified in isolation.
function NotificationTestHarness({
  bus,
  notifications,
  deepLinkTask,
  canvasEnabled,
}: {
  bus: NotificationBus | null;
  notifications: INotifications | null;
  deepLinkTask: Task | undefined;
  canvasEnabled: boolean;
}) {
  const nativeUnavailable = !notifications;
  // Deep links (OS URL scheme) and the dock are desktop concepts; hide those
  // test rows on cloud-only hosts. Clicking a native notification still opens
  // its task in-app on web.
  const { localWorkspaces } = useHostCapabilities();

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
    <>
      <Text className="mt-4 mb-1 block border-gray-6 border-t pt-4 font-medium text-sm">
        Test
      </Text>
      <Text color="gray" className="mb-1 text-[13px]">
        Fire each delivery channel directly to check it works end to end.
        {nativeUnavailable
          ? " Native notifications aren't available on this host."
          : ""}
      </Text>

      <SettingRow
        label="In-app toast"
        description={`Shows an in-app toast — the tier used when the app is focused but you're not on the relevant task${canvasEnabled ? " or canvas" : ""}.`}
      >
        <Button variant="soft" size="1" onClick={testToast} disabled={!bus}>
          Send
        </Button>
      </SettingRow>

      {localWorkspaces && (
        <SettingRow
          label="Deep-link toast"
          description={
            deepLinkTask
              ? `Toast with a "View" action that opens "${deepLinkTask.title}".`
              : "Run a task first to test deep-linking from a toast."
          }
        >
          <Button
            variant="soft"
            size="1"
            onClick={testToastDeepLink}
            disabled={!bus || !deepLinkTask}
          >
            Send
          </Button>
        </SettingRow>
      )}

      <SettingRow
        label="Native OS notification"
        description="Shows a system notification — the tier used when the app is in the background."
        noBorder={!localWorkspaces}
      >
        <Button
          variant="soft"
          size="1"
          onClick={testNative}
          disabled={nativeUnavailable}
        >
          Send
        </Button>
      </SettingRow>

      {localWorkspaces && (
        <SettingRow
          label="Deep-link notification"
          description={
            deepLinkTask
              ? `Fires a native notification that opens "${deepLinkTask.title}" when clicked.`
              : "Run a task first to test deep-linking from a notification."
          }
        >
          <Button
            variant="soft"
            size="1"
            onClick={testNativeDeepLink}
            disabled={nativeUnavailable || !deepLinkTask}
          >
            Send
          </Button>
        </SettingRow>
      )}

      {localWorkspaces && (
        <SettingRow
          label="Dock badge"
          description="Adds the unread dot to the dock icon (clears on next focus)."
        >
          <Button
            variant="soft"
            size="1"
            onClick={() => notifications?.showUnreadIndicator()}
            disabled={nativeUnavailable}
          >
            Show
          </Button>
        </SettingRow>
      )}

      {localWorkspaces && (
        <SettingRow
          label="Dock bounce"
          description="Bounces the dock icon once to request attention."
          noBorder
        >
          <Button
            variant="soft"
            size="1"
            onClick={() => notifications?.requestAttention()}
            disabled={nativeUnavailable}
          >
            Bounce
          </Button>
        </SettingRow>
      )}
    </>
  );
}
