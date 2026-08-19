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
