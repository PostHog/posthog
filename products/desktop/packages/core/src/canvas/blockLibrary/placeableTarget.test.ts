import { describe, expect, it } from "vitest";
import type { DropPlace } from "./sourceEdits";
import { placeableTarget } from "./sourceEdits";

const FILE = "src/canvas.tsx";
const SOURCE = `function Game() {
  return (
    <div>
      <h2>Title</h2>
    </div>
  )
}

export default function Canvas() {
  return (
    <main>
      <Card title="A" />
    </main>
  )
}
`;
const ROOT = {
  file: FILE,
  start: SOURCE.indexOf("<main>"),
  end: SOURCE.indexOf("</main>") + "</main>".length,
};
const TITLE = {
  file: FILE,
  start: SOURCE.indexOf("<h2>"),
  end: SOURCE.indexOf("</h2>") + "</h2>".length,
};
const CARD = {
  file: FILE,
  start: SOURCE.indexOf("<Card"),
  end: SOURCE.indexOf("/>") + 2,
};

describe("placeableTarget", () => {
  it.each<[string, { start: number; end: number }, DropPlace, boolean]>([
    ["inside the root", ROOT, "inside", true],
    ["after the root", ROOT, "after", false],
    ["before the root", ROOT, "before", false],
    ["after a child of the root", CARD, "after", true],
    [
      "after an element of a component defined outside the root",
      TITLE,
      "after",
      true,
    ],
    [
      "at offsets that no longer point at JSX",
      { start: 0, end: 20 },
      "after",
      false,
    ],
  ])("%s", (_name, range, place, expected) => {
    expect(
      placeableTarget(
        { files: { [FILE]: SOURCE }, rootSource: ROOT },
        { file: FILE, ...range, place },
      ),
    ).toBe(expected);
  });
});
