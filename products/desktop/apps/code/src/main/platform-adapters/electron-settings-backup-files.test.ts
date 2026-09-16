// @vitest-environment node
import "reflect-metadata";
import * as fsPromises from "node:fs/promises";
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
vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs/promises")>();
  return { ...actual, rename: vi.fn(actual.rename) };
});

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

  it("replaces an existing backup on Windows even when rename first refuses to overwrite it", async () => {
    const directory = await mkdtemp(join(tmpdir(), "posthog-backup-test-"));
    directories.push(directory);
    const filePath = join(directory, "settings.json");
    await writeFile(filePath, "old backup");
    dialogs.showSaveDialog.mockResolvedValue({ canceled: false, filePath });
    const rename = vi.mocked(fsPromises.rename);
    rename.mockImplementationOnce(async () => {
      throw Object.assign(new Error("EPERM"), { code: "EPERM" });
    });
    const originalPlatform = process.platform;
    Object.defineProperty(process, "platform", { value: "win32" });
    try {
      const files = new ElectronSettingsBackupFiles();
      expect(
        await files.save({
          contents: "new backup",
          defaultName: "backup.json",
        }),
      ).toBe(true);
    } finally {
      Object.defineProperty(process, "platform", { value: originalPlatform });
    }
    expect(await readFile(filePath, "utf8")).toBe("new backup");
  });

  it("restores the existing backup if the Windows retry also fails", async () => {
    const directory = await mkdtemp(join(tmpdir(), "posthog-backup-test-"));
    directories.push(directory);
    const filePath = join(directory, "settings.json");
    await writeFile(filePath, "old backup");
    dialogs.showSaveDialog.mockResolvedValue({ canceled: false, filePath });
    const rename = vi.mocked(fsPromises.rename);
    const { rename: realRename } =
      await vi.importActual<typeof import("node:fs/promises")>(
        "node:fs/promises",
      );
    let attemptsOntoDestination = 0;
    rename.mockImplementation(async (from, to, ...rest) => {
      // Moving the existing backup aside, and restoring it, are real; only
      // the rename of the new temp file onto the destination is faked, for
      // both the initial attempt and the retry.
      if (typeof from !== "string" || !from.endsWith(".tmp"))
        return realRename(from, to, ...rest);
      attemptsOntoDestination++;
      throw Object.assign(new Error(`attempt ${attemptsOntoDestination}`), {
        code: attemptsOntoDestination === 1 ? "EPERM" : "EBUSY",
      });
    });
    const originalPlatform = process.platform;
    Object.defineProperty(process, "platform", { value: "win32" });
    try {
      const files = new ElectronSettingsBackupFiles();
      await expect(
        files.save({ contents: "new backup", defaultName: "backup.json" }),
      ).rejects.toThrow("attempt 2");
    } finally {
      Object.defineProperty(process, "platform", { value: originalPlatform });
      rename.mockImplementation(realRename);
    }
    expect(await readFile(filePath, "utf8")).toBe("old backup");
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
