import { z } from "zod";
import {
  AUTO_COMPACT_MAX_PERCENT,
  AUTO_COMPACT_MIN_PERCENT,
} from "../sessions/autoCompact";

export const SETTINGS_BACKUP_FORMAT_VERSION = 1;
export const MAX_SETTINGS_BACKUP_BYTES = 64 * 1024 * 1024;
export const MAX_SETTINGS_BACKUP_ENTRIES = 1_000;
export const MAX_CUSTOM_SOUND_BYTES = 1_000_000;
export const MAX_CUSTOM_SOUND_DURATION_MS = 5_000;
export const DURATION_TOLERANCE_MS = 300;

export const completionSoundSchema = z.union([
  z.enum([
    "none",
    "guitar",
    "danilo",
    "revi",
    "meep",
    "meep-smol",
    "bubbles",
    "drop",
    "knock",
    "ring",
    "shoot",
    "slide",
    "switch",
    "wilhelm",
    "icq",
    "msn",
    "random-all",
    "random-custom",
  ]),
  z
    .string()
    .regex(/^custom:.+$/)
    .transform((value) => value as `custom:${string}`),
]);

const audioDataUrlSchema = z
  .string()
  .max(Math.ceil(MAX_CUSTOM_SOUND_BYTES / 3) * 4 + 200)
  .refine((value) => {
    const match =
      /^data:(?:audio\/[a-z0-9.+-]+|application\/octet-stream)(?:;codecs=[a-z0-9.,-]+)?;base64,([A-Za-z0-9+/]+={0,2})$/i.exec(
        value,
      );
    if (!match || !match[1] || match[1].length % 4 !== 0) return false;
    const data = match[1];
    const padding = data.endsWith("==") ? 2 : data.endsWith("=") ? 1 : 0;
    return (data.length * 3) / 4 - padding <= MAX_CUSTOM_SOUND_BYTES;
  }, "Expected embedded audio of 1 MB or less");

export const customSoundSchema = z.object({
  id: z.string().min(1).max(256),
  name: z.string().min(1).max(256),
  dataUrl: audioDataUrlSchema,
  durationMs: z
    .number()
    .positive()
    .max(MAX_CUSTOM_SOUND_DURATION_MS + DURATION_TOLERANCE_MS),
});
export type CustomSound = z.infer<typeof customSoundSchema>;
export type CompletionSound = z.infer<typeof completionSoundSchema>;

const text = z.string().max(20_000);
const nullableText = text.nullable();
const messagingMode = z.enum(["queue", "steer"]);

// This allowlist is the portable contract. Account state, credentials, caches,
// paths and preferences owned by the operating system must not cross machines.
// Machine-local safety controls stay off it too, even though they are
// preferences: allowBypassPermissions normally requires an explicit consent
// dialog, and spendLimits guards against runaway spend, so a backup file must
// not be able to change either without the user seeing it happen.
export const portableSettingsSchema = z
  .object({
    theme: z.enum(["light", "dark", "system"]),
    defaultRunMode: z.enum(["local", "cloud", "last_used"]),
    lastUsedRunMode: z.enum(["local", "cloud"]),
    lastUsedLocalWorkspaceMode: z.enum(["worktree", "local"]),
    lastUsedWorkspaceMode: z.enum(["worktree", "local", "cloud"]),
    lastUsedAgentRuntime: z.enum(["acp", "pi"]),
    lastUsedAdapter: z.enum(["claude", "codex"]),
    lastUsedModel: nullableText,
    lastUsedPiModel: nullableText,
    lastUsedReasoningEffort: nullableText,
    lastUsedContextWindow: z.enum(["200k", "1m"]).nullable(),
    lastUsedFastMode: z.boolean().nullable(),
    defaultInitialTaskMode: z.enum(["plan", "last_used"]),
    defaultReasoningEffort: z.enum([
      "last_used",
      "low",
      "medium",
      "high",
      "xhigh",
      "max",
      "ultracode",
    ]),
    defaultMessagingMode: messagingMode,
    defaultCloudMessagingMode: messagingMode,
    desktopNotifications: z.boolean(),
    dockBadgeNotifications: z.boolean(),
    dockBounceNotifications: z.boolean(),
    toastNotifications: z.boolean(),
    completionSound: completionSoundSchema,
    completionVolume: z.number().min(0).max(100),
    scaleSoundWithTaskLength: z.boolean(),
    spokenNotifications: z.boolean(),
    spokenNotifyNeedsInput: z.boolean(),
    spokenNotifyCompletion: z.boolean(),
    spokenNotifyProgress: z.boolean(),
    spokenFocusMode: z.enum(["always", "unviewed_task", "app_unfocused"]),
    elevenLabsVoiceId: text,
    autoConvertLongText: z.enum(["off", "1000", "2500", "5000", "10000"]),
    sendMessagesWith: z.enum(["enter", "cmd+enter"]),
    customInstructions: text,
    ste100Enabled: z.boolean(),
    diffOpenMode: z.enum(["auto", "split", "same-pane", "last-active-pane"]),
    warnOnMidSessionModelSwitch: z.boolean(),
    autoCompactPercent: z
      .number()
      .min(AUTO_COMPACT_MIN_PERCENT)
      .max(AUTO_COMPACT_MAX_PERCENT)
      .nullable(),
    debugLogsCloudRuns: z.boolean(),
    autoPublishCloudRuns: z.boolean(),
    rtkEnabledLocal: z.boolean(),
    rtkEnabledCloud: z.boolean(),
    terminalFont: z.enum([
      "berkeley-mono",
      "jetbrains-mono",
      "system",
      "custom",
    ]),
    terminalCustomFontFamily: text,
    terminalGpuRendering: z.boolean(),
    showSidebarWorktrees: z.boolean(),
    hedgehogMode: z.boolean(),
    slotMachineMode: z.boolean(),
    brainrotMode: z.boolean(),
    downloadUpdatesAutomatically: z.boolean(),
    dismissibleUpdateBanners: z.boolean(),
    tipsEnabled: z.boolean(),
  })
  .partial();
export type PortableSettings = z.infer<typeof portableSettingsSchema>;

export const settingsBackupSchema = z.object({
  format: z.literal("posthog-desktop-settings"),
  formatVersion: z.number().int().positive(),
  appVersion: z.string().min(1).max(100),
  exportedAt: z.iso.datetime(),
  settings: z
    .record(z.string(), z.unknown())
    .refine(
      (settings) => Object.keys(settings).length <= MAX_SETTINGS_BACKUP_ENTRIES,
    ),
  sounds: z.array(z.unknown()).max(MAX_SETTINGS_BACKUP_ENTRIES),
});
export type SettingsBackup = z.infer<typeof settingsBackupSchema>;

export const saveSettingsBackupInput = z.object({
  contents: z.string().max(MAX_SETTINGS_BACKUP_BYTES),
  defaultName: z
    .string()
    .regex(/^posthog-(?:settings|sounds)-\d{4}-\d{2}-\d{2}\.json$/),
});
