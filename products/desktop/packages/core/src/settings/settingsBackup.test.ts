import "reflect-metadata";
import type { ISettingsBackupFiles } from "@posthog/platform/settings-backup-files";
import { describe, expect, it, vi } from "vitest";
import {
  type CustomSound,
  MAX_CUSTOM_SOUND_BYTES,
  type SettingsBackup,
} from "./schemas";
import {
  SettingsBackupService,
  type SettingsBackupSnapshot,
} from "./settingsBackup";

const clip = (overrides: Partial<CustomSound> = {}): CustomSound => ({
  id: "clip-a",
  name: "My chime",
  dataUrl: "data:audio/wav;base64,UklGRg==",
  durationMs: 1000,
  ...overrides,
});
const backup = (overrides: Partial<SettingsBackup> = {}): SettingsBackup => ({
  format: "posthog-desktop-settings",
  formatVersion: 1,
  appVersion: "1.0.0",
  exportedAt: "2026-01-01T12:00:00.000Z",
  settings: {
    completionSound: "custom:clip-a",
    completionVolume: 65,
    scaleSoundWithTaskLength: true,
    theme: "dark",
  },
  sounds: [clip()],
  ...overrides,
});

function setup(
  initial: SettingsBackupSnapshot = {
    settings: { theme: "light", completionSound: "none" },
    sounds: [],
  },
) {
  let snapshot = initial;
  let saved = "";
  const files: ISettingsBackupFiles = {
    getAppVersion: async () => "2.0.0",
    open: async () => saved,
    save: async ({ contents }) => {
      saved = contents;
      return true;
    },
  };
  const apply = vi.fn((patch: SettingsBackupSnapshot) => {
    snapshot = {
      settings: { ...snapshot.settings, ...patch.settings },
      sounds: patch.sounds,
    };
  });
  const service = new SettingsBackupService(
    { read: () => snapshot, apply },
    files,
  );
  const rename = (from: string, to: string) => {
    snapshot = {
      ...snapshot,
      sounds: snapshot.sounds.map((sound) =>
        sound.name === from ? { ...sound, name: to } : sound,
      ),
    };
  };
  return {
    service,
    files,
    apply,
    rename,
    read: () => snapshot,
    saved: () => saved,
  };
}

describe("SettingsBackupService", () => {
  it("round-trips embedded clips, names, selection and playback settings onto a fresh machine", async () => {
    const source = setup({
      settings: {
        ...backup().settings,
        customInstructions: "Use short sentences.",
      },
      sounds: [
        clip(),
        clip({
          id: "clip-b",
          name: "Second chime",
          dataUrl: "data:audio/webm;codecs=opus;base64,AQID",
        }),
      ],
    });
    await source.service.exportBackup("all");
    const exported = JSON.parse(source.saved());
    expect(exported).toMatchObject({ appVersion: "2.0.0", formatVersion: 1 });
    const target = setup();
    const review = target.service.inspect(source.saved(), "2.0.0");
    expect(review.warnings).toEqual([]);
    expect(await target.service.importBackup(review, "all")).toBe(2);
    expect(target.read()).toEqual(source.read());
  });

  it("preserves destination sounds, remaps a conflicting selection, and makes repeat imports idempotent", async () => {
    const existing = clip({
      name: "Keep this clip",
      dataUrl: "data:audio/wav;base64,AQID",
    });
    const target = setup({ settings: { theme: "light" }, sounds: [existing] });
    const review = target.service.inspect(JSON.stringify(backup()), "2.0.0");
    await target.service.importBackup(review, "all");
    const imported = target
      .read()
      .sounds.find((sound) => sound.name === "My chime");
    expect(target.read().sounds[0]).toEqual(existing);
    expect(imported?.id).not.toBe(existing.id);
    expect(target.read().settings.completionSound).toBe(
      `custom:${imported?.id}`,
    );
    expect(await target.service.importBackup(review, "all")).toBe(0);
    expect(target.read().sounds).toHaveLength(2);
    // A rename keeps the clip's audio, so a later import of the same file
    // must still recognize the clip and keep the destination name.
    target.rename("My chime", "My ding");
    expect(await target.service.importBackup(review, "all")).toBe(0);
    expect(target.read().sounds.map((sound) => sound.name)).toEqual([
      "Keep this clip",
      "My ding",
    ]);
  });

  it("exports only allowed preferences and keeps sounds-only transfers independent of other settings", async () => {
    const source = setup({
      settings: {
        theme: "dark",
        completionVolume: 45,
        completionSound: "random-custom",
        ...{
          elevenLabsKeyConfigured: true,
          lastUsedCloudRepository: "example/repo",
          secret: "fake-token",
        },
      },
      sounds: [clip()],
    });
    await source.service.exportBackup("all");
    expect(JSON.parse(source.saved()).settings).toEqual({
      theme: "dark",
      completionVolume: 45,
      completionSound: "random-custom",
    });
    await source.service.exportBackup("sounds");
    expect(JSON.parse(source.saved()).settings).toEqual({
      completionVolume: 45,
      completionSound: "random-custom",
    });
    const target = setup();
    await target.service.importBackup(
      target.service.inspect(source.saved(), "2.0.0"),
      "sounds",
    );
    expect(target.read().settings).toEqual({
      theme: "light",
      completionVolume: 45,
      completionSound: "random-custom",
    });
  });

  it("warns about removed and changed fields without importing them or invoking unsafe keys", async () => {
    const target = setup();
    const review = target.service.inspect(
      JSON.stringify(
        backup({
          settings: JSON.parse(
            '{"theme":"dark","completionVolume":101,"removedPreference":true,"__proto__":{"polluted":true},"elevenLabsKeyConfigured":true}',
          ),
        }),
      ),
      "2.0.0",
    );
    expect(review.warnings.map(({ key, reason }) => [key, reason])).toEqual([
      ["completionVolume", "changed"],
      ["removedPreference", "unknown"],
      ["elevenLabsKeyConfigured", "unknown"],
    ]);
    await target.service.importBackup(review, "all");
    expect(target.read().settings).toEqual({
      theme: "dark",
      completionSound: "none",
    });
  });

  it("keeps the instructions on this machine when the backup carries none", async () => {
    const target = setup({
      settings: { theme: "light", customInstructions: "Use short sentences." },
      sounds: [],
    });
    const review = target.service.inspect(
      JSON.stringify(
        backup({ settings: { theme: "dark", customInstructions: "" } }),
      ),
      "2.0.0",
    );

    expect(review.settings.customInstructions).toBeUndefined();
    await target.service.importBackup(review, "all");
    expect(target.read().settings.customInstructions).toBe(
      "Use short sentences.",
    );
  });

  it.each<[string, string, boolean]>([
    ["path traversal", "../convai/knowledge-base/text", false],
    ["extra path segment", "voice/other", false],
    ["query string", "voice?output_format=mp3", false],
    ["fragment", "voice#tail", false],
    ["plain token", "goT3UYdM9bhm0n2lmKQx", true],
  ])(
    "checks an imported voice id: %s",
    async (_name, elevenLabsVoiceId, accepted) => {
      const target = setup();
      const review = target.service.inspect(
        JSON.stringify(backup({ settings: { elevenLabsVoiceId } })),
        "2.0.0",
      );
      expect(review.warnings).toEqual(
        accepted ? [] : [{ key: "elevenLabsVoiceId", reason: "changed" }],
      );
      await target.service.importBackup(review, "all");
      expect(target.read().settings.elevenLabsVoiceId).toBe(
        accepted ? elevenLabsVoiceId : undefined,
      );
    },
  );

  it.each([
    ["missing clip", [], "custom:clip-a"],
    ["empty random library", [], "random-custom"],
    [
      "remote audio",
      [clip({ dataUrl: "https://example.com/chime.wav" })],
      "custom:clip-a",
    ],
    [
      "broken base64",
      [clip({ dataUrl: "data:audio/wav;base64,invalid!!" })],
      "custom:clip-a",
    ],
    [
      "oversized clip",
      [
        clip({
          dataUrl: `data:audio/wav;base64,${Buffer.alloc(MAX_CUSTOM_SOUND_BYTES + 1).toString("base64")}`,
        }),
      ],
      "custom:clip-a",
    ],
  ])(
    "keeps the current selection when the backup has %s",
    async (_name, sounds, selection) => {
      const target = setup({
        settings: { completionSound: "guitar" },
        sounds: [clip({ id: "local" })],
      });
      const review = target.service.inspect(
        JSON.stringify(
          backup({ sounds, settings: { completionSound: selection } }),
        ),
        "2.0.0",
      );
      expect(
        review.warnings.some((warning) => warning.reason === "selection"),
      ).toBe(true);
      await target.service.importBackup(review, "all");
      expect(target.read().settings.completionSound).toBe("guitar");
      expect(target.read().sounds).toHaveLength(1);
    },
  );

  it("keeps valid clips when another clip is invalid or has a duplicate ID", async () => {
    const target = setup();
    const review = target.service.inspect(
      JSON.stringify(
        backup({
          sounds: [
            clip(),
            clip({ name: "Duplicate" }),
            clip({ id: "other", durationMs: -1 }),
          ],
        }),
      ),
      "2.0.0",
    );
    expect(review.warnings).toHaveLength(2);
    await target.service.importBackup(review, "all");
    expect(target.read().sounds).toEqual([clip()]);
  });

  it.each([
    ["invalid JSON", "not JSON"],
    ["invalid shape", "[]"],
    ["future format", JSON.stringify(backup({ formatVersion: 2 }))],
    [
      "too many sounds",
      JSON.stringify(
        backup({ sounds: Array.from({ length: 1001 }, () => null) }),
      ),
    ],
    [
      "oversized setting key",
      JSON.stringify(backup({ settings: { ["k".repeat(257)]: true } })),
    ],
    [
      "too many settings",
      JSON.stringify(
        backup({
          settings: Object.fromEntries(
            Array.from({ length: 1001 }, (_, index) => [
              `unknown-${index}`,
              true,
            ]),
          ),
        }),
      ),
    ],
  ])(
    "rejects invalid or future formats without writes: %s",
    (_name, contents) => {
      const target = setup();
      expect(() => target.service.inspect(contents, "2.0.0")).toThrow();
      expect(target.apply).not.toHaveBeenCalled();
    },
  );

  it("treats canceled dialogs as cancellation and releases the operation guard after a save failure", async () => {
    const target = setup();
    target.files.open = async () => null;
    expect(await target.service.openBackup()).toBeNull();
    target.files.save = async () => {
      throw new Error("Disk full");
    };
    await expect(target.service.exportBackup("all")).rejects.toThrow(
      "Disk full",
    );
    target.files.save = async () => false;
    expect(await target.service.exportBackup("all")).toBe(false);
    expect(target.apply).not.toHaveBeenCalled();
  });

  it.each(["export", "open", "import"] as const)(
    "blocks %s while an export is running",
    async (operation) => {
      const target = setup();
      let finish!: (version: string) => void;
      target.files.getAppVersion = () =>
        new Promise<string>((resolve) => {
          finish = resolve;
        });
      const review = target.service.inspect(JSON.stringify(backup()), "2.0.0");
      const exporting = target.service.exportBackup("all");
      const operations = {
        export: () => target.service.exportBackup("all"),
        open: () => target.service.openBackup(),
        import: () => target.service.importBackup(review, "all"),
      };
      await expect(operations[operation]()).rejects.toThrow("already running");
      finish("2.0.0");
      await exporting;
    },
  );

  it("rejects a sound library that exceeds the import limit before saving", async () => {
    const target = setup({
      settings: {},
      sounds: Array.from({ length: 1001 }, (_, index) =>
        clip({ id: `clip-${index}` }),
      ),
    });
    await expect(target.service.exportBackup("sounds")).rejects.toThrow(
      "1,000",
    );
    expect(target.saved()).toBe("");
  });
});
