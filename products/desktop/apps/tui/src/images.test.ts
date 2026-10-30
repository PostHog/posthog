import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { droppedImages } from "./images";

const droppedImage = (sequence: string) => droppedImages(sequence)[0];

describe("droppedImage", () => {
  const folder = mkdtempSync(join(tmpdir(), "tui images "));
  const png = join(folder, "shot.png");
  writeFileSync(png, "hi");
  writeFileSync(join(folder, "notes.txt"), "hi");
  const paste = (text: string): string => `\x1b[200~${text}\x1b[201~`;

  it("reads every image in a drop of several files, escaped or quoted, and skips what is not an image", () => {
    const second = join(folder, "second shot.jpg");
    writeFileSync(second, "yo");
    const escaped = (path: string) => path.replaceAll(" ", "\\ ");
    const dropped = droppedImages(
      paste(
        `${escaped(png)} ${escaped(second)} '${join(folder, "notes.txt")}' ${escaped(join(folder, "gone.png"))}`,
      ),
    );
    expect(dropped.map((image) => [image.mimeType, image.data])).toEqual([
      ["image/png", "aGk="],
      ["image/jpeg", "eW8="],
    ]);
  });

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
