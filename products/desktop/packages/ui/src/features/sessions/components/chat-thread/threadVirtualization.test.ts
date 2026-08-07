import type { ConversationItem } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { describe, expect, it } from "vitest";
import type { ToolGroupItem } from "./ToolGroup";
import {
  type AgentTurn,
  computeStickyAnchor,
  countFlatRows,
  flattenTurnRows,
  nextThreadFollowState,
  type StickyAnchorEntry,
  sampleThreadScroll,
  type ThreadScrollSample,
  type TurnRow,
} from "./threadVirtualization";

type SessionUpdateItem = Extract<ConversationItem, { type: "session_update" }>;

function userMessage(id: string): ConversationItem {
  return { type: "user_message", id, content: `msg ${id}`, timestamp: 1 };
}

function sessionUpdate(
  id: string,
  {
    turnComplete = false,
    timestamp,
    text,
  }: { turnComplete?: boolean; timestamp?: number; text?: string } = {},
): SessionUpdateItem {
  return {
    type: "session_update",
    id,
    update: {
      sessionUpdate: "agent_message_chunk",
      content: { type: "text", text: text ?? `text ${id}` },
    } as SessionUpdateItem["update"],
    turnContext: {
      toolCalls: new Map(),
      childItems: new Map(),
      turnCancelled: false,
      turnComplete,
    },
    timestamp,
  };
}

function toolGroup(id: string, tools: SessionUpdateItem[]): ToolGroupItem {
  return { type: "tool_group", id, items: tools };
}

function agentTurn(
  id: string,
  items: TurnRow[],
  prompt?: ConversationItem,
): AgentTurn {
  return { type: "agent_turn", id, items: items as AgentTurn["items"], prompt };
}

describe("flattenTurnRows", () => {
  it("passes standalone rows through with ordinal keys for user messages", () => {
    const rows: TurnRow[] = [
      userMessage("u1"),
      { type: "git_action", id: "g1", actionType: "commit" as never },
      userMessage("u2"),
    ];
    const flat = flattenTurnRows(rows);
    expect(flat.map((r) => r.key)).toEqual([
      "user-turn-0",
      "g1",
      "user-turn-1",
    ]);
    expect(flat.every((r) => !r.inTurn && !r.isTrailingInTurn)).toBe(true);
  });

  it("flattens an agent turn to one row per item, flagging only the last as trailing", () => {
    const a = sessionUpdate("a");
    const b = toolGroup("b", [sessionUpdate("b1"), sessionUpdate("b2")]);
    const c = sessionUpdate("c");
    const flat = flattenTurnRows([
      userMessage("u1"),
      agentTurn("a", [a, b, c]),
    ]);
    expect(flat.map((r) => r.key)).toEqual(["user-turn-0", "a", "b", "c"]);
    expect(flat.map((r) => r.inTurn)).toEqual([false, true, true, true]);
    expect(flat.map((r) => r.isTrailingInTurn)).toEqual([
      false,
      false,
      false,
      true,
    ]);
  });

  it("puts the completion timestamp only on the last row of a completed turn", () => {
    const done = agentTurn("d", [
      sessionUpdate("d1"),
      sessionUpdate("d2", { turnComplete: true, timestamp: 1234 }),
    ]);
    const flat = flattenTurnRows([done]);
    expect(flat.map((r) => r.turnTimestamp)).toEqual([undefined, 1234]);
  });

  it("carries the turn's copy text on the same row as its timestamp", () => {
    const done = agentTurn("d", [
      sessionUpdate("d1", { text: "first" }),
      sessionUpdate("d2", {
        turnComplete: true,
        timestamp: 1234,
        text: "last",
      }),
    ]);
    const flat = flattenTurnRows([done]);
    expect(flat.map((r) => r.turnCopyText)).toEqual([
      undefined,
      "first\n\nlast",
    ]);
  });

  it("copies only the agent response", () => {
    const done = agentTurn(
      "d",
      [
        sessionUpdate("d1", {
          turnComplete: true,
          timestamp: 1,
          text: "reply",
        }),
      ],
      userMessage("u1"),
    );
    expect(flattenTurnRows([done]).at(-1)?.turnCopyText).toBe("reply");
  });

  it("leaves copy text off a turn that is still streaming", () => {
    const streaming = agentTurn("s", [
      sessionUpdate("s1", { text: "partial" }),
    ]);
    expect(flattenTurnRows([streaming])[0].turnCopyText).toBeUndefined();
  });

  it("reads a trailing tool group's timestamp from its last tool", () => {
    const turn = agentTurn("t", [
      sessionUpdate("t1"),
      toolGroup("t2", [
        sessionUpdate("t2a"),
        sessionUpdate("t2b", { turnComplete: true, timestamp: 99 }),
      ]),
    ]);
    const flat = flattenTurnRows([turn]);
    expect(flat.at(-1)?.turnTimestamp).toBe(99);
  });

  it("leaves the timestamp unset while the turn is still streaming", () => {
    const streaming = agentTurn("s", [
      sessionUpdate("s1"),
      sessionUpdate("s2", { turnComplete: false }),
    ]);
    const flat = flattenTurnRows([streaming]);
    expect(flat.every((r) => r.turnTimestamp === undefined)).toBe(true);
  });
});

describe("countFlatRows", () => {
  it("matches the length flattenTurnRows produces", () => {
    const rows: TurnRow[] = [
      userMessage("u1"),
      agentTurn("a", [sessionUpdate("a1"), sessionUpdate("a2")]),
      userMessage("u2"),
      { type: "git_action", id: "g1", actionType: "commit" as never },
      agentTurn("b", [
        sessionUpdate("b1"),
        toolGroup("b2", [sessionUpdate("b2a")]),
        sessionUpdate("b3"),
      ]),
    ];
    expect(countFlatRows(rows)).toBe(flattenTurnRows(rows).length);
    expect(countFlatRows(rows)).toBe(8);
  });

  it("is zero for an empty thread", () => {
    expect(countFlatRows([])).toBe(0);
  });
});

describe("nextThreadFollowState", () => {
  const sample = (
    over: Partial<ThreadScrollSample> = {},
  ): ThreadScrollSample => ({
    atEnd: false,
    atExactEnd: false,
    scrolledUp: false,
    scrolledDown: false,
    farFromEnd: false,
    ...over,
  });

  it.each([
    [
      "holds following while an append measures short of the end",
      { following: true, leftEnd: false },
      sample(),
      { following: true, leftEnd: false },
    ],
    [
      "drops following once the reader scrolls up past the tolerance",
      { following: true, leftEnd: false },
      sample({ scrolledUp: true }),
      { following: false, leftEnd: false },
    ],
    [
      "drops following when the end has drifted far below the fold",
      { following: true, leftEnd: false },
      sample({ farFromEnd: true }),
      { following: false, leftEnd: false },
    ],
    [
      "re-arms inside the tolerance when the reader never left the end",
      { following: false, leftEnd: false },
      sample({ atEnd: true }),
      { following: true, leftEnd: false },
    ],
    [
      "stays off when streamed content grows past a reader parked inside the tolerance",
      { following: false, leftEnd: true },
      sample({ atEnd: true }),
      { following: false, leftEnd: true },
    ],
    [
      "resumes when the reader scrolls back down into the tolerance",
      { following: false, leftEnd: true },
      sample({ atEnd: true, scrolledDown: true }),
      { following: true, leftEnd: false },
    ],
    [
      "ignores a downward scroll that stops short of the tolerance",
      { following: false, leftEnd: true },
      sample({ scrolledDown: true }),
      { following: false, leftEnd: true },
    ],
    [
      "resumes once the reader is back against the bottom",
      { following: false, leftEnd: true },
      sample({ atEnd: true, atExactEnd: true }),
      { following: true, leftEnd: false },
    ],
    [
      "drops following on an upward scroll that stays inside the tolerance",
      { following: true, leftEnd: false },
      sample({ atEnd: true, scrolledUp: true }),
      { following: false, leftEnd: false },
    ],
  ])("%s", (_name, state, event, expected) => {
    expect(nextThreadFollowState(state, event)).toEqual(expected);
  });
});

describe("sampleThreadScroll", () => {
  // Scroll range is 0..1500.
  const viewport = (scrollTop: number) => ({
    scrollTop,
    scrollHeight: 2000,
    clientHeight: 500,
  });

  it.each([
    [
      "a downward move that stops just short of the bottom",
      1450,
      1400,
      { atEnd: true, atExactEnd: false, scrolledDown: true },
    ],
    [
      "a downward move that stops outside the tolerance",
      1300,
      1200,
      { atEnd: false, atExactEnd: false, scrolledDown: true },
    ],
    [
      "sub-pixel drift, which is neither direction",
      900,
      900.5,
      { atEnd: false, atExactEnd: false, scrolledDown: false },
    ],
    [
      "the true bottom",
      1500,
      1450,
      { atEnd: true, atExactEnd: true, scrolledDown: true },
    ],
  ])("measures %s", (_name, scrollTop, previous, expected) => {
    expect(sampleThreadScroll(viewport(scrollTop), previous)).toMatchObject(
      expected,
    );
  });
});

describe("computeStickyAnchor", () => {
  const entries: StickyAnchorEntry[] = [
    { id: "u1", start: 0, end: 100 },
    { id: "u2", start: 500, end: 620 },
    { id: "u3", start: 2000, end: 2080 },
  ];

  it("returns no anchor when scrolled above every user row", () => {
    // u1 starts inside the peek band at scrollTop 0, so scroll "above" means a
    // list whose first user row starts below the band.
    const below: StickyAnchorEntry[] = [{ id: "u1", start: 300, end: 400 }];
    expect(computeStickyAnchor(below, 0, 64)).toEqual({
      anchorId: null,
    });
  });

  it("keeps the anchor visible while its row is still on screen", () => {
    expect(computeStickyAnchor(entries, 40, 64)).toEqual({
      anchorId: "u1",
    });
  });

  it("keeps the anchor once its bottom clears the viewport top", () => {
    expect(computeStickyAnchor(entries, 120, 64)).toEqual({
      anchorId: "u1",
    });
  });

  it("picks the last user row above the peek band", () => {
    expect(computeStickyAnchor(entries, 900, 64)).toEqual({
      anchorId: "u2",
    });
    expect(computeStickyAnchor(entries, 2000, 64)).toEqual({
      anchorId: "u3",
    });
  });

  it("counts a row entering the peek band as the new anchor", () => {
    // u2 starts at 500; at scrollTop 440 its top sits 60px below the viewport
    // top, inside the 64px band.
    expect(computeStickyAnchor(entries, 440, 64)).toEqual({
      anchorId: "u2",
    });
  });
});
