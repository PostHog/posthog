import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { cleanupAllPinnedSettings, pinnedSettingsDir } from "./pinned-settings";

describe("cleanupAllPinnedSettings", () => {
  let configDir: string;
  let saved: string | undefined;
  beforeEach(() => {
    saved = process.env.CLAUDE_CONFIG_DIR;
    configDir = fs.mkdtempSync(path.join(os.tmpdir(), "pinned-settings-"));
    process.env.CLAUDE_CONFIG_DIR = configDir;
  });
  afterEach(() => {
    if (saved === undefined) delete process.env.CLAUDE_CONFIG_DIR;
    else process.env.CLAUDE_CONFIG_DIR = saved;
    fs.rmSync(configDir, { recursive: true, force: true });
  });

  it("removes leftover session files and nothing else", async () => {
    const dir = pinnedSettingsDir();
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, "s-1.json"), "{}");
    fs.writeFileSync(path.join(dir, "s-2.json"), "{}");
    fs.writeFileSync(path.join(dir, "notes.txt"), "keep");
    const outside = path.join(configDir, "settings.json");
    fs.writeFileSync(outside, "{}");

    await cleanupAllPinnedSettings();

    expect(fs.readdirSync(dir)).toEqual(["notes.txt"]);
    expect(fs.existsSync(outside)).toBe(true);
  });

  it("does nothing when the directory is missing", async () => {
    await expect(cleanupAllPinnedSettings()).resolves.toBeUndefined();
  });
});
