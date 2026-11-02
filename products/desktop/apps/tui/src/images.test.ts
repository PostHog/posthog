import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { droppedAttachments, withFilePaths } from "./images";

const droppedImage = (sequence: string) => droppedAttachments(sequence)[0];

describe("droppedImage", () => {
  const folder = mkdtempSync(join(tmpdir(), "tui images "));
  const png = join(folder, "shot.png");
  writeFileSync(png, "hi");
  writeFileSync(join(folder, "notes.txt"), "hi");
  const paste = (text: string): string => `\x1b[200~${text}\x1b[201~`;

  it("reads every file in a drop, escaped or quoted: images by their bytes, the rest by path, folders skipped", () => {
    const second = join(folder, "second shot.jpg");
    writeFileSync(second, "yo");
    const escaped = (path: string) => path.replaceAll(" ", "\\ ");
    const dropped = droppedAttachments(
      paste(
        `${escaped(png)} ${escaped(second)} '${join(folder, "notes.txt")}' ${escaped(folder)} ${escaped(join(folder, "gone.png"))}`,
      ),
    );
    expect(dropped).toEqual([
      { type: "image", mimeType: "image/png", data: "aGk=" },
      { type: "image", mimeType: "image/jpeg", data: "eW8=" },
      { type: "file", path: join(folder, "notes.txt"), name: "notes.txt" },
    ]);
    expect(
      withFilePaths("read [File #1: notes.txt] and [Image #1]", dropped),
    ).toBe(`read ${join(folder, "notes.txt")} and [Image #1]`);
  });

  it("reads a drop the terminal sends unbracketed, with a narrow no-break space it never escapes, as macOS names screenshots", () => {
    // macOS puts U+202F before am/pm in a screenshot's name; Terminal escapes the ASCII spaces around it only.
    const second = join(folder, "shot at 2.27\u202fpm.jpg");
    writeFileSync(second, "yo");
    const escaped = (path: string) => path.replaceAll(" ", "\\ ");
    const dropped = droppedAttachments(`${escaped(png)} ${escaped(second)}`);
    expect(
      dropped.map((a) => (a.type === "image" ? a.mimeType : a.path)),
    ).toEqual(["image/png", "image/jpeg"]);
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
    expect(image?.type === "image" ? image.mimeType : undefined).toBe(mimeType);
    if (mimeType) expect(image?.type === "image" && image.data).toBe("aGk=");
  });
});
