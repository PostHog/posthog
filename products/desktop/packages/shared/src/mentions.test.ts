import { describe, expect, it } from "vitest";
import {
  formatMention,
  mentionsToPlainText,
  splitMentionSegments,
} from "./mentions";

describe("formatMention", () => {
  it("serializes name and email into a token", () => {
    expect(formatMention("Raquel Smith", "raquel@posthog.com")).toBe(
      "@[Raquel Smith](raquel@posthog.com)",
    );
  });

  it.each([
    ["strips brackets from names", "A [b] c", "a@x.com", "@[A  b  c](a@x.com)"],
    [
      "falls back to the email local part",
      "[]",
      "ann@x.com",
      "@[ann](ann@x.com)",
    ],
  ])("%s", (_label, name, email, expected) => {
    expect(formatMention(name, email)).toBe(expected);
  });

  it("round-trips through the parser", () => {
    const token = formatMention("Raquel Smith", "raquel@posthog.com");
    const segments = splitMentionSegments(`hey ${token}!`);
    expect(segments).toEqual([
      { type: "text", text: "hey " },
      {
        type: "mention",
        text: token,
        name: "Raquel Smith",
        email: "raquel@posthog.com",
      },
      { type: "text", text: "!" },
    ]);
  });
});

describe("splitMentionSegments", () => {
  it("returns a single text segment when there are no mentions", () => {
    expect(splitMentionSegments("no mentions here")).toEqual([
      { type: "text", text: "no mentions here" },
    ]);
  });

  it("handles adjacent and repeated mentions", () => {
    const content = "@[A](a@x.com)@[B](b@x.com) and @[A](a@x.com)";
    const segments = splitMentionSegments(content);
    expect(segments.map((s) => s.type)).toEqual([
      "mention",
      "mention",
      "text",
      "mention",
    ]);
  });

  it("ignores markdown links and bare @ text", () => {
    const content = "see [docs](https://x.com) and email me @ home";
    expect(splitMentionSegments(content)).toEqual([
      { type: "text", text: content },
    ]);
  });

  it("ignores malformed tokens", () => {
    for (const content of [
      "@[no email]()",
      "@[unclosed](a@x.com",
      "@[](a@x.com)",
      "@[spaced email](a b@x.com)",
      "@[double at](a@@x.com)",
    ]) {
      expect(
        splitMentionSegments(content).every((s) => s.type === "text"),
      ).toBe(true);
    }
  });

  it("scans adversarial unterminated tokens in linear time", () => {
    // Regression for CodeQL js/polynomial-redos: with `@` allowed around the
    // email separator this input backtracked quadratically.
    const content = `@[Z](${"!@".repeat(50_000)}`;
    const start = performance.now();
    const segments = splitMentionSegments(content);
    expect(performance.now() - start).toBeLessThan(500);
    expect(segments).toEqual([{ type: "text", text: content }]);
  });
});

describe("mentionsToPlainText", () => {
  it("flattens tokens to @Name", () => {
    expect(mentionsToPlainText("hi @[Ann Lee](ann@x.com), ship it")).toBe(
      "hi @Ann Lee, ship it",
    );
  });
});
