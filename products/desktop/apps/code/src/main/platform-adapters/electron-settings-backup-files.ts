import { randomUUID } from "node:crypto";
import { open, rename, unlink, writeFile } from "node:fs/promises";
import { MAX_SETTINGS_BACKUP_BYTES } from "@posthog/core/settings/schemas";
import type { ISettingsBackupFiles } from "@posthog/platform/settings-backup-files";
import { app, dialog } from "electron";
import { injectable } from "inversify";
import { resolveDialogParent } from "./electron-dialog";

@injectable()
export class ElectronSettingsBackupFiles implements ISettingsBackupFiles {
  async getAppVersion(): Promise<string> {
    return app.getVersion();
  }

  async open(): Promise<string | null> {
    const parent = resolveDialogParent();
    const options = {
      title: "Import settings and sounds",
      filters: [{ name: "PostHog backup", extensions: ["json"] }],
      properties: ["openFile" as const],
    };
    const result = parent
      ? await dialog.showOpenDialog(parent, options)
      : await dialog.showOpenDialog(options);
    if (result.canceled || !result.filePaths[0]) return null;
    const file = await open(result.filePaths[0], "r");
    try {
      const stat = await file.stat();
      if (!stat.isFile() || stat.size > MAX_SETTINGS_BACKUP_BYTES)
        throw new Error("Choose a PostHog backup file of 64 MB or less.");
      // Bound the read even if another process grows the file after stat().
      const buffer = Buffer.alloc(stat.size + 1);
      let size = 0;
      while (size < buffer.length) {
        const { bytesRead } = await file.read(
          buffer,
          size,
          buffer.length - size,
          null,
        );
        if (bytesRead === 0) break;
        size += bytesRead;
      }
      if (size > stat.size)
        throw new Error(
          "The backup changed while it was being read. Choose the file again.",
        );
      return buffer.subarray(0, size).toString("utf8");
    } finally {
      await file.close();
    }
  }

  async save(input: {
    contents: string;
    defaultName: string;
  }): Promise<boolean> {
    if (Buffer.byteLength(input.contents, "utf8") > MAX_SETTINGS_BACKUP_BYTES)
      throw new Error(
        "This backup exceeds 64 MB. Remove unused clips and try again.",
      );
    const parent = resolveDialogParent();
    const options = {
      title: "Export settings and sounds",
      defaultPath: input.defaultName,
      filters: [{ name: "PostHog backup", extensions: ["json"] }],
    };
    const result = parent
      ? await dialog.showSaveDialog(parent, options)
      : await dialog.showSaveDialog(options);
    if (result.canceled || !result.filePath) return false;
    const temporary = `${result.filePath}.${randomUUID()}.tmp`;
    try {
      await writeFile(temporary, input.contents, {
        encoding: "utf8",
        mode: 0o600,
        flag: "wx",
      });
      await this.replace(temporary, result.filePath);
    } finally {
      await unlink(temporary).catch(() => {});
    }
    return true;
  }

  /**
   * Windows can refuse to rename onto an existing file (EPERM/EEXIST) even
   * though the save dialog already confirmed the overwrite; POSIX rename
   * replaces the destination outright. Move the existing destination aside
   * rather than deleting it outright, so a retry that also fails still has
   * something to restore instead of losing both the old and new backups.
   */
  private async replace(temporary: string, destination: string): Promise<void> {
    try {
      await rename(temporary, destination);
      return;
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (
        process.platform !== "win32" ||
        (code !== "EPERM" && code !== "EEXIST")
      )
        throw error;
    }
    const recovery = `${destination}.${randomUUID()}.bak`;
    await rename(destination, recovery);
    try {
      await rename(temporary, destination);
    } catch (error) {
      await rename(recovery, destination).catch(() => {});
      throw error;
    }
    await unlink(recovery).catch(() => {});
  }
}
