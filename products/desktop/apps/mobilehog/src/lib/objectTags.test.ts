import type { Token } from "marked";
import { describe, expect, it } from "vitest";
import { lexMarkdown } from "./markdown";
import { isObjectTagMarkup, objectWebUrl } from "./objectTags";

// The token tree without raw source, so cases read as structure.
function shape(text: string): unknown {
  return JSON.parse(
    JSON.stringify(lexMarkdown(text), (key, value) =>
      key === "raw" || key === "escaped" ? undefined : value,
    ),
  );
}

function inline(text: string): Token[] {
  const [paragraph] = lexMarkdown(text) as { tokens: Token[] }[];
  return paragraph.tokens;
}

describe("object tags in markdown", () => {
  it("turns an inline tag into a reference with its label", () => {
    expect(
      inline('See <insight id="9pQx3">checkout funnel</insight> now'),
    ).toEqual([
      expect.objectContaining({ type: "text", text: "See " }),
      expect.objectContaining({
        type: "objectRef",
        ref: { kind: "insight", id: "9pQx3", label: "checkout funnel" },
      }),
      expect.objectContaining({ type: "text", text: " now" }),
    ]);
  });

  it.each([
    ['<flag id="42"/>', { kind: "flag", id: "42", label: "42" }],
    [
      '<hogql label="errors today">SELECT 1</hogql>',
      { kind: "hogql", id: "SELECT 1", label: "errors today" },
    ],
    [
      '<feature_flag id="7">beta</feature_flag>',
      { kind: "flag", id: "7", label: "beta" },
    ],
  ])("reads %s", (tag, ref) => {
    expect(inline(`x ${tag}`)[1]).toEqual(
      expect.objectContaining({ type: "objectRef", ref }),
    );
  });

  it("renders only the label of an unknown kind", () => {
    expect(inline('x <gizmo id="1">Gizmo</gizmo>')[1]).toEqual(
      expect.objectContaining({ type: "text", text: "Gizmo" }),
    );
  });

  it("leaves other html alone", () => {
    expect(inline("x <b>bold</b>")[1]).toEqual(
      expect.objectContaining({ type: "html", text: "<b>" }),
    );
  });

  it.each([
    [
      '<insight id="9pQx3" display="block"/>',
      { mode: "insight", shortId: "9pQx3" },
    ],
    [
      '<hogql display="block" title="DAU">SELECT count() FROM events</hogql>',
      { mode: "hogql", query: "SELECT count() FROM events", title: "DAU" },
    ],
    [
      '<hogql display="block" title="DAU">\nSELECT 1\n\nFROM events\n</hogql>',
      { mode: "hogql", query: "SELECT 1\n\nFROM events", title: "DAU" },
    ],
  ])("turns a block tag on its own line into a card: %s", (text, spec) => {
    expect(shape(text)).toEqual([{ type: "objectCard", spec }]);
  });

  it("keeps a block tag inside a sentence as a reference", () => {
    expect(inline('Look: <insight id="a" display="block"/>')[1]).toEqual(
      expect.objectContaining({ type: "objectRef" }),
    );
  });

  it("renders a block tag of a kind without a card as a reference", () => {
    expect(shape('<dashboard id="7" display="block"/>')).toEqual([
      {
        type: "paragraph",
        text: '<dashboard id="7" display="block"/>',
        tokens: [
          {
            type: "objectRef",
            ref: { kind: "dashboard", id: "7", label: "7" },
          },
        ],
      },
    ]);
  });

  it("caps the cards in one message and resets for the next", () => {
    const text = Array.from(
      { length: 12 },
      (_, i) => `<insight id="i${i}" display="block"/>`,
    ).join("\n\n");
    const cards = (source: string) =>
      lexMarkdown(source).filter((token) => token.type === "objectCard").length;
    expect(cards(text)).toBe(10);
    expect(cards(text)).toBe(10);
  });

  it("keeps tags in code literal", () => {
    expect(
      shape(
        '`<insight id="x"/>`\n\n```\n<insight id="x" display="block"/>\n```',
      ),
    ).toEqual([
      expect.objectContaining({
        type: "paragraph",
        tokens: [{ type: "codespan", text: '<insight id="x"/>' }],
      }),
      { type: "space" },
      { type: "code", lang: "", text: '<insight id="x" display="block"/>' },
    ]);
  });
});

describe("isObjectTagMarkup", () => {
  it.each([
    ['<insight id="x">', true],
    ["</insight>", true],
    ['<hogql display="block">', true],
    ["<b>", false],
    ["<br/>", false],
  ])("%s -> %s", (html, expected) => {
    expect(isObjectTagMarkup(html)).toBe(expected);
  });
});

describe("objectWebUrl", () => {
  it.each([
    ["insight", "9pQx3", "https://us.posthog.com/project/2/insights/9pQx3"],
    [
      "hogql",
      "SELECT 1 & 2",
      "https://us.posthog.com/project/2/sql?open_query=SELECT%201%20%26%202",
    ],
    ["flag", "42", "https://us.posthog.com/project/2/feature_flags/42"],
    ["flag", "my-flag", null],
    ["gizmo", "1", null],
  ])("%s %s", (kind, id, expected) => {
    expect(objectWebUrl("https://us.posthog.com/", 2, kind, id)).toBe(expected);
  });
});
