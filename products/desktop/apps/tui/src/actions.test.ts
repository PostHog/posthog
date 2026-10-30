import { describe, expect, it } from "vitest";
import { canRun, openActions, pickerKey } from "./actions";
import type { ShowAction, TranscriptLine } from "./transcript";

const compose: ShowAction = {
  kind: "compose",
  label: "Try again",
  prompt: "Add tracing",
};
const inbox = { kind: "open_inbox", label: "Open inbox" } as ShowAction;
const actions: TranscriptLine = {
  kind: "actions",
  id: "x",
  actions: [compose, inbox],
};
const user: TranscriptLine = { kind: "user", id: "u", text: "hi" };
const reply: TranscriptLine = {
  kind: "assistant",
  id: "a",
  text: "Here you go",
};

describe("openActions", () => {
  it.each([
    ["the agent's latest actions", [user, actions, reply], "x"],
    ["no actions", [user, reply], null],
    ["actions the user has replied past", [user, actions, reply, user], null],
  ])("finds %s", (_, lines, id) => {
    expect(openActions(lines as TranscriptLine[])?.id ?? null).toBe(id);
  });
});

describe("canRun", () => {
  it("runs compose here and leaves desktop screens to the desktop app", () => {
    expect([compose, inbox].map(canRun)).toEqual([true, false]);
  });
});

describe("pickerKey", () => {
  it.each([
    ["\x1b[A", "up"],
    ["\x1b[B", "down"],
    ["\r", "choose"],
    ["\x1b", "dismiss"],
    ["a", null],
  ])("maps %j", (sequence, expected) => {
    expect(pickerKey(sequence)).toBe(expected);
  });
});
