import { describe, expect, test } from "vitest";
import { formatInlineComments } from "./comment-formatter.js";
import type { EnrichedEvent, EnrichedFlag, EnrichedListItem } from "./types.js";

function eventItem(
  name: string,
  line: number,
  inJsx: boolean,
): EnrichedListItem {
  return {
    type: "event",
    line,
    name,
    method: "capture",
    inJsx,
    verified: true,
  };
}

function enrichedEvent(name: string): EnrichedEvent {
  return {
    eventName: name,
    verified: true,
  } as EnrichedEvent;
}

describe("formatInlineComments", () => {
  test("pure JS line uses // suffix", () => {
    const source = `posthog.capture('a');`;
    const items = [eventItem("a", 0, false)];
    const events = new Map([["a", enrichedEvent("a")]]);
    const out = formatInlineComments(
      source,
      "javascript",
      items,
      new Map<string, EnrichedFlag>(),
      events,
    );
    expect(out).toBe(
      `posthog.capture('a'); // [PostHog] Event: "a" \u2014 (verified)`,
    );
  });

  test("pure JSX line uses {/* */} suffix", () => {
    const source = `<Button onClick={() => track('a')} />`;
    const items = [eventItem("a", 0, true)];
    const events = new Map([["a", enrichedEvent("a")]]);
    const out = formatInlineComments(
      source,
      "javascript",
      items,
      new Map<string, EnrichedFlag>(),
      events,
    );
    expect(out).toBe(
      `<Button onClick={() => track('a')} /> {/* [PostHog] Event: "a" \u2014 (verified) */}`,
    );
  });

  test("mixed JSX and JS items on the same line fall back to a leading JSX comment", () => {
    const source = `  <Button onClick={() => track('a')} />; posthog.capture('b');`;
    const items = [eventItem("a", 0, true), eventItem("b", 0, false)];
    const events = new Map([
      ["a", enrichedEvent("a")],
      ["b", enrichedEvent("b")],
    ]);
    const out = formatInlineComments(
      source,
      "javascript",
      items,
      new Map<string, EnrichedFlag>(),
      events,
    );
    const lines = out.split("\n");
    expect(lines).toHaveLength(2);
    expect(lines[0]).toBe(
      `  {/* [PostHog] Event: "b" \u2014 (verified) | Event: "a" \u2014 (verified) */}`,
    );
    expect(lines[1]).toBe(source);
  });

  test("multiple mixed-context lines insert leading comments without shifting indices", () => {
    const source = [
      `<A onClick={() => track('a')} />; posthog.capture('b');`,
      `const x = 1;`,
      `<C onClick={() => track('c')} />; posthog.capture('d');`,
    ].join("\n");
    const items = [
      eventItem("a", 0, true),
      eventItem("b", 0, false),
      eventItem("c", 2, true),
      eventItem("d", 2, false),
    ];
    const events = new Map([
      ["a", enrichedEvent("a")],
      ["b", enrichedEvent("b")],
      ["c", enrichedEvent("c")],
      ["d", enrichedEvent("d")],
    ]);
    const out = formatInlineComments(
      source,
      "javascript",
      items,
      new Map<string, EnrichedFlag>(),
      events,
    );
    const lines = out.split("\n");
    expect(lines).toHaveLength(5);
    expect(lines[0]).toMatch(/^\{\/\* \[PostHog\] .*"b".*"a".* \*\/\}$/);
    expect(lines[1]).toBe(
      `<A onClick={() => track('a')} />; posthog.capture('b');`,
    );
    expect(lines[2]).toBe(`const x = 1;`);
    expect(lines[3]).toMatch(/^\{\/\* \[PostHog\] .*"d".*"c".* \*\/\}$/);
    expect(lines[4]).toBe(
      `<C onClick={() => track('c')} />; posthog.capture('d');`,
    );
  });
});
