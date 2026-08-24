import { describe, expect, it } from "vitest";
import { buildTaskNamingSource } from "./taskDescription";

const PASTED = "/tmp/clip/attachment-a1b2c3/pasted-text.txt";
const SHOT = "/tmp/clip/attachment-d4e5f6/shot.png";
const NOTES = "/tmp/clip/attachment-j0k1l2/notes.txt";
const BLANK = "/tmp/clip/attachment-m3n4o5/blank.txt";
const GONE = "/tmp/clip/attachment-g7h8i9/gone.txt";

const files: Record<string, string> = {
  [PASTED]: "Deploy blocks on a stale lockfile\nSecond line",
  [NOTES]: "Extra context line",
  [BLANK]: "   ",
};

const fileReadClient = {
  readAbsoluteFile: (filePath: string) =>
    Promise.resolve(files[filePath] ?? null),
};

describe("buildTaskNamingSource", () => {
  it.each([
    [
      "names from pasted text behind a cloud attachment summary",
      "Attached files: pasted-text.txt",
      [PASTED],
      "Deploy blocks on a stale lockfile\nSecond line",
    ],
    [
      "names from pasted text behind a local file tag",
      `<file path="${PASTED}" />`,
      [PASTED],
      "Deploy blocks on a stale lockfile\nSecond line",
    ],
    [
      "joins multiple readable files",
      "Attached files: pasted-text.txt, notes.txt",
      [PASTED, NOTES],
      "Deploy blocks on a stale lockfile\nSecond line\n\nExtra context line",
    ],
    [
      "falls back to the file name for a binary attachment",
      "Attached files: shot.png",
      [SHOT],
      "[Attached: shot.png]",
    ],
    [
      "falls back to the file name for an unreadable attachment",
      "Attached files: gone.txt",
      [GONE],
      "[Attached: gone.txt]",
    ],
    [
      "falls back to the file name for a whitespace-only attachment",
      "Attached files: blank.txt",
      [BLANK],
      "[Attached: blank.txt]",
    ],
  ])("%s", async (_name, description, filePaths, expected) => {
    await expect(
      buildTaskNamingSource(description, filePaths, fileReadClient),
    ).resolves.toBe(expected);
  });

  it.each([
    ["a typed prompt", "Fix the login redirect", [PASTED]],
    [
      "a typed prompt with an attachment summary",
      "Fix the login redirect\n\nAttached files: pasted-text.txt",
      [PASTED],
    ],
    ["no attachments", "Attached files: pasted-text.txt", []],
  ])("returns undefined for %s", async (_name, description, filePaths) => {
    await expect(
      buildTaskNamingSource(description, filePaths, fileReadClient),
    ).resolves.toBeUndefined();
  });
});
