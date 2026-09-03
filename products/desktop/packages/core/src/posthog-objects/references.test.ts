import { describe, expect, it } from "vitest";
import { extractPostHogObjectReferences } from "./references";

describe("extractPostHogObjectReferences", () => {
  it.each([
    [
      '<insight id="9pQx3">Checkout funnel</insight>',
      [{ kind: "insight", id: "9pQx3", label: "Checkout funnel" }],
    ],
    [
      '<feature-flag id="new-checkout" display="block" />',
      [{ kind: "flag", id: "new-checkout", label: "new-checkout" }],
    ],
    [
      '<hogql label="Errors today">SELECT count() FROM events</hogql>',
      [
        {
          kind: "hogql",
          id: "SELECT count() FROM events",
          label: "Errors today",
        },
      ],
    ],
  ] as const)("extracts a complete object tag", (markdown, expected) => {
    expect(extractPostHogObjectReferences(markdown)).toEqual(expected);
  });

  it("ignores tags in code and deduplicates the completed message", () => {
    const tag = '<insight id="9pQx3">Checkout funnel</insight>';
    expect(
      extractPostHogObjectReferences(
        [`\`${tag}\``, "```xml", tag, "```", tag, tag].join("\n"),
      ),
    ).toEqual([{ kind: "insight", id: "9pQx3", label: "Checkout funnel" }]);
  });

  it.each([
    [
      "tilde fence",
      ["~~~", '<insight id="9pQx3">Checkout funnel</insight>', "~~~"],
    ],
    [
      "nested longer backtick fence",
      [
        "````",
        "```",
        '<insight id="9pQx3">Checkout funnel</insight>',
        "```",
        "````",
      ],
    ],
    [
      "multi-backtick inline span",
      ['``<insight id="9pQx3">Checkout funnel</insight>``'],
    ],
  ] as const)(
    "ignores tags the renderer shows as code inside a %s",
    (_label, lines) => {
      expect(extractPostHogObjectReferences(lines.join("\n"))).toEqual([]);
    },
  );

  it("stays fast on many unmatched opening tags", () => {
    const hostile = `${'<insight id="x">'.repeat(20_000)}\n<flag id="real" />`;
    const start = performance.now();
    const references = extractPostHogObjectReferences(hostile);
    expect(performance.now() - start).toBeLessThan(1_000);
    expect(references).toEqual([{ kind: "flag", id: "real", label: "real" }]);
  });

  it("stays fast on many unmatched backtick runs", () => {
    const hostile = Array.from(
      { length: 400 },
      (_, index) => `${"`".repeat(index + 1)}a`,
    ).join("");
    const start = performance.now();
    const references = extractPostHogObjectReferences(
      `${hostile.repeat(4)}\n<flag id="real" />`,
    );
    expect(performance.now() - start).toBeLessThan(1_000);
    expect(references).toEqual([{ kind: "flag", id: "real", label: "real" }]);
  });

  it("ignores partial, unknown, and oversized references", () => {
    expect(
      extractPostHogObjectReferences(
        [
          '<insight id="partial">Checkout',
          '<unknown id="1">Unknown</unknown>',
          `<event id="${"x".repeat(16_385)}" />`,
        ].join("\n"),
      ),
    ).toEqual([]);
  });
});
