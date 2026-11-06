import { describe, expect, it } from "vitest";
import { setJsxAttributes } from "./sourceEdits";

const FILE = "src/canvas.tsx";

function edit(
  source: string,
  values: Record<string, string | number | boolean | string[] | undefined>,
): string {
  const start = source.indexOf("<Panel");
  const end = source.lastIndexOf(">") + 1;
  return (
    setJsxAttributes({ [FILE]: source }, { file: FILE, start, end }, values)[
      FILE
    ] ?? ""
  );
}

describe("setJsxAttributes", () => {
  it.each([
    {
      name: "replaces a string prop and keeps expression props",
      source:
        '<Panel title="Old" range={dateRange} onPick={(v) => set({ v })} />',
      values: { title: "New" },
      expected:
        '<Panel title="New" range={dateRange} onPick={(v) => set({ v })} />',
    },
    {
      name: "adds a prop to a self-closing tag",
      source: "<Panel {...shared} />",
      values: { limit: 5 },
      expected: "<Panel {...shared} limit={5} />",
    },
    {
      name: "removes a prop",
      source: '<Panel title="A" breakdown="$browser" />',
      values: { breakdown: undefined },
      expected: '<Panel title="A" />',
    },
    {
      name: "edits only the opening tag of an element with children",
      source: '<Panel title="A">\n  <Child title="B" />\n</Panel>',
      values: { title: "C", steps: ["a", "b"] },
      expected:
        '<Panel title="C" steps={["a","b"]}>\n  <Child title="B" />\n</Panel>',
    },
    {
      name: "keeps a string with quotes valid",
      source: '<Panel title="A" />',
      values: { title: 'Say "hi"' },
      expected: '<Panel title={"Say \\"hi\\""} />',
    },
  ])("$name", ({ source, values, expected }) => {
    expect(edit(source, values)).toBe(expected);
  });
});
