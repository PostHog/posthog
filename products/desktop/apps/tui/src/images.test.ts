import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { droppedImage } from "./images";

describe("droppedImage", () => {
  const folder = mkdtempSync(join(tmpdir(), "tui images "));
  const png = join(folder, "shot.png");
  writeFileSync(png, "hi");
  writeFileSync(join(folder, "notes.txt"), "hi");
  const paste = (text: string): string => `\x1b[200~${text}\x1b[201~`;

  it.each([
    [
      "a path with escaped spaces",
      paste(png.replaceAll(" ", "\\ ")),
      "image/png",
    ],
    ["a quoted path", paste(`'${png}'`), "image/png"],
    [
      "a file that is not an image",
      paste(join(folder, "notes.txt")),
      undefined,
    ],
    [
      "an image that does not exist",
      paste(join(folder, "gone.png")),
      undefined,
    ],
    ["pasted text", paste("see shot.png"), undefined],
    ["a typed key", "a", undefined],
  ])("reads %s", (_, sequence, mimeType) => {
    const image = droppedImage(sequence);
    expect(image?.mimeType).toBe(mimeType);
    if (mimeType) expect(image?.data).toBe("aGk=");
  });
});
