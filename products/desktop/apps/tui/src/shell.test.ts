import { describe, expect, it } from "vitest";
import { parseShell, shellBlocked } from "./shell";

describe("parseShell", () => {
  it.each([
    ["!ls -la", "ls -la"],
    ["  ! git status  ", "git status"],
    ["!", null],
    ["!   ", null],
    ["hello !ls", null],
    ["/model", null],
  ])("reads %j", (text, expected) => {
    expect(parseShell(text)).toBe(expected);
  });
});

describe("shellBlocked", () => {
  const live = { status: "in_progress" };
  it.each([
    [
      "no chat yet",
      { taskId: null, isLocal: false, run: undefined },
      "Start a chat first",
    ],
    ["a local chat", { taskId: "t", isLocal: true, run: undefined }, null],
    [
      "a cloud chat without a run",
      { taskId: "t", isLocal: false, run: undefined },
      "no run",
    ],
    [
      "an ended cloud run",
      { taskId: "t", isLocal: false, run: { status: "completed" } },
      "has ended",
    ],
    ["a running cloud run", { taskId: "t", isLocal: false, run: live }, null],
  ])("for %s", (_, chat, expected) => {
    const reason = shellBlocked({ ...chat, canControl: true });
    if (expected === null) expect(reason).toBeNull();
    else expect(reason).toContain(expected);
  });
});
