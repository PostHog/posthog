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

  it.each([
    [
      "a labeled link",
      "The [Checkout funnel](https://us.posthog.com/project/2/insights/9pQx3) dropped.",
      [{ kind: "insight", id: "9pQx3", label: "Checkout funnel" }],
    ],
    [
      "a SQL link with nested parentheses",
      "[Errors](https://us.posthog.com/project/2/sql?open_query=SELECT%20count(if(x))%20FROM%20events)",
      [
        {
          kind: "hogql",
          id: "SELECT count(if(x)) FROM events",
          label: "Errors",
        },
      ],
    ],
    [
      "a SQL link with raw spaces in angle brackets",
      "[Errors](<https://us.posthog.com/project/2/sql?open_query=SELECT count() FROM events>)",
      [{ kind: "hogql", id: "SELECT count() FROM events", label: "Errors" }],
    ],
    [
      "a bare URL at the end of a sentence",
      "See https://us.posthog.com/project/2/feature_flags/42.",
      [{ kind: "flag", id: "42", label: "Feature flag 42" }],
    ],
    [
      "a link in another project",
      "[x](https://us.posthog.com/project/3/insights/9pQx3)",
      [],
    ],
    [
      "a link in inline code",
      "`[x](https://us.posthog.com/project/2/insights/9pQx3)`",
      [],
    ],
  ] as const)("extracts %s", (_name, markdown, expected) => {
    expect(
      extractPostHogObjectReferences(markdown, {
        appUrl: "https://us.posthog.com",
        projectId: 2,
      }),
    ).toEqual(expected);
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
    [
      "indented code block",
      ["Example:", "", '    <insight id="9pQx3">Checkout funnel</insight>'],
    ],
  ] as const)(
    "ignores tags the renderer shows as code inside a %s",
    (_label, lines) => {
      expect(extractPostHogObjectReferences(lines.join("\n"))).toEqual([]);
    },
  );

  it("keeps tags indented under a list item", () => {
    expect(
      extractPostHogObjectReferences(
        [
          "1. Signups",
          "",
          '    <insight id="9pQx3">Checkout funnel</insight>',
        ].join("\n"),
      ),
    ).toEqual([{ kind: "insight", id: "9pQx3", label: "Checkout funnel" }]);
  });

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
