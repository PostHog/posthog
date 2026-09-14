// @vitest-environment node
import "reflect-metadata";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";

const dialogs = vi.hoisted(() => ({
  showOpenDialog: vi.fn(),
  showSaveDialog: vi.fn(),
}));
vi.mock("electron", () => ({
  app: { getVersion: () => "1.2.3" },
  dialog: dialogs,
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
}));

import { ElectronSettingsBackupFiles } from "./electron-settings-backup-files";

const directories: string[] = [];
afterEach(async () => {
  await Promise.all(
    directories
      .splice(0)
      .map((path) => rm(path, { recursive: true, force: true })),
  );
  vi.clearAllMocks();
});

describe("ElectronSettingsBackupFiles", () => {
  it("saves and reads the complete backup through the selected native paths", async () => {
    const directory = await mkdtemp(join(tmpdir(), "posthog-backup-test-"));
    directories.push(directory);
    const filePath = join(directory, "settings.json");
    await writeFile(filePath, "old backup");
    dialogs.showSaveDialog.mockResolvedValue({ canceled: false, filePath });
    dialogs.showOpenDialog.mockResolvedValue({
      canceled: false,
      filePaths: [filePath],
    });
    const files = new ElectronSettingsBackupFiles();
    const contents = JSON.stringify({
      sounds: [
        { name: "Test chime", dataUrl: "data:audio/wav;base64,UklGRg==" },
      ],
    });
    expect(
      await files.save({
        contents,
        defaultName: "posthog-settings-2026-01-01.json",
      }),
    ).toBe(true);
    expect(await readFile(filePath, "utf8")).toBe(contents);
    expect(await files.open()).toBe(contents);
  });

  it("leaves an existing backup untouched when the save dialog is canceled", async () => {
    const directory = await mkdtemp(join(tmpdir(), "posthog-backup-test-"));
    directories.push(directory);
    const filePath = join(directory, "settings.json");
    await writeFile(filePath, "keep this backup");
    dialogs.showSaveDialog.mockResolvedValue({ canceled: true, filePath });
    const files = new ElectronSettingsBackupFiles();
    expect(
      await files.save({ contents: "replacement", defaultName: "backup.json" }),
    ).toBe(false);
    expect(await readFile(filePath, "utf8")).toBe("keep this backup");
  });
});
