import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { describe, expect, it } from "vitest";
import {
  type Briefing,
  type BriefingItem,
  DEFAULT_REPORT_QUESTIONS,
  greeting,
  TodayClient,
  type TodayState,
  todayHitAt,
  todayLines,
} from "./today";

const item = (key: string, label: string, state = "open"): BriefingItem => ({
  key: `report:${key}`,
  label,
  title: `Title of ${label}`,
  url: `/project/2/inbox/${key}`,
  state,
});
const pause = item("r1", "workflow schedule pause");
const indexing = item("r2", "mobile report indexing", "dismissed");
const briefing: Briefing = {
  status: "ready",
  headline: "Two reports need your attention.",
  paragraphs: [
    [
      { text: "The ", item_key: null, highlight: false },
      { text: pause.label, item_key: pause.key, highlight: true },
      { text: " is ready for review.", item_key: null, highlight: false },
    ],
    [
      { text: "The ", item_key: null, highlight: false },
      { text: indexing.label, item_key: indexing.key, highlight: false },
      { text: " waits for you.", item_key: null, highlight: false },
    ],
  ],
  items: [pause, indexing],
  more_reports_count: 40,
};
const ready: TodayState = { kind: "ready", briefing, firstName: "Harley" };
const plain = (lines: string[]): string[] =>
  lines.map((line) => stripTerminalSequences(line));

describe("greeting", () => {
  it.each([
    [3, "You're up late, Harley."],
    [9, "Morning, Harley."],
    [14, "Afternoon, Harley."],
    [20, "Evening, Harley."],
  ])("greets at %i o'clock", (hour, text) => {
    expect(greeting(hour, "Harley")).toBe(text);
  });
});

describe("todayLines", () => {
  it("lays out the greeting, headline, progress, paragraphs and Inbox line", () => {
    expect(plain(todayLines(ready, 80, 9).lines)).toEqual([
      "",
      "  Morning, Harley.",
      "",
      "  Two reports need your attention.",
      "  1 of 2 done",
      "",
      "  The workflow schedule pause is ready for review.",
      "",
      "  The mobile report indexing waits for you.",
      "",
      "  40 more for you in the Inbox. Or ask PostHog AI to walk you through it.",
    ]);
  });

  it("finds each link where it was drawn, across a wrap", () => {
    const { lines, hits } = todayLines(ready, 24, 9);
    const text = plain(lines);
    const at = (word: string): [number, number] => {
      const row = text.findIndex((line) => line.includes(word));
      return [row, text[row].indexOf(word)];
    };

    const [first, start] = at("workflow");
    const [second, end] = at("pause");
    expect(text.every((line) => line.length <= 24)).toBe(true);
    expect(second).toBeGreaterThan(first);
    expect(todayHitAt(hits, first, start - 1)).toBeNull();
    expect(todayHitAt(hits, first, start)).toEqual({
      kind: "item",
      item: pause,
    });
    expect(todayHitAt(hits, second, end + 4)).toEqual({
      kind: "item",
      item: pause,
    });
    expect(todayHitAt(hits, second, end + 5)).toBeNull();
    expect(todayHitAt(hits, ...at("ready"))).toBeNull();
    expect(todayHitAt(hits, ...at("Inbox"))).toEqual({ kind: "inbox" });
    expect(todayHitAt(hits, ...at("walk"))).toEqual({ kind: "ask" });
  });

  it.each([
    ["loading", { kind: "loading" }, "Reading what changed in your project…"],
    [
      "a project without Today",
      { kind: "error", reason: "unavailable" },
      "Today isn't available for this project. Type below to start a chat.",
    ],
    [
      "a sign-in without Today's scopes",
      { kind: "error", reason: "signIn" },
      "Sign out with /logout and sign in again to see Today.",
    ],
    [
      "a briefing still being written",
      {
        kind: "ready",
        briefing: { ...briefing, status: "writing", paragraphs: [] },
        firstName: null,
      },
      "Writing today's briefing…",
    ],
  ] as [string, TodayState, string][])("explains %s", (_, state, text) => {
    expect(plain(todayLines(state, 80, 9).lines).join("\n")).toContain(text);
  });
});

describe("TodayClient", () => {
  const client = (respond: (url: string) => Response) =>
    new TodayClient(
      async (url) => respond(url),
      "https://us.posthog.com",
      async () => ({ teamId: 2, firstName: "Harley" }),
      "Europe/London",
    );

  it.each([
    [404, { kind: "error", reason: "unavailable" }],
    [403, { kind: "error", reason: "signIn" }],
    [500, { kind: "error", reason: "failed" }],
  ])("reads a %i as why Today cannot show", async (status, state) => {
    expect(await client(() => new Response("", { status })).load()).toEqual(
      state,
    );
  });

  it("reads the briefing for the project in the user's time zone", async () => {
    const urls: string[] = [];
    const state = await client((url) => {
      urls.push(url);
      return Response.json(briefing);
    }).load();

    expect(urls).toEqual([
      "https://us.posthog.com/api/projects/2/today/briefing/?timezone=Europe%2FLondon",
    ]);
    expect(state).toEqual(ready);
  });

  it.each([
    ["the report's own questions", ["What broke?"], ["What broke?"]],
    ["the defaults when it has none", [], DEFAULT_REPORT_QUESTIONS],
  ])("offers %s", async (_, suggested, questions) => {
    const today = client(() => Response.json({ suggested_prompts: suggested }));
    expect(await today.questions(pause)).toEqual(questions);
  });
});
