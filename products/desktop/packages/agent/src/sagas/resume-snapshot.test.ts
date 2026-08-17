import { describe, expect, it } from "vitest";
import { parseResumeSnapshot } from "./resume-saga";

describe("parseResumeSnapshot", () => {
  const conversation = [
    { role: "user", content: [{ type: "text", text: "hi" }] },
  ];

  it("accepts a complete snapshot and derives the latest checkpoint", () => {
    const parsed = parseResumeSnapshot({
      conversation,
      latestGitCheckpoints: [
        { checkpointId: "cp-1", checkpointRef: "ref-1" },
        { checkpointId: "cp-2", checkpointRef: "ref-2" },
      ],
      logEntryCount: 42,
      sessionId: "session-1",
    });

    expect(parsed?.latestGitCheckpoint?.checkpointId).toBe("cp-2");
    expect(parsed?.logEntryCount).toBe(42);
    expect(parsed?.sessionId).toBe("session-1");
  });

  it.each([
    ["null", null],
    ["a string", "nope"],
    ["a missing conversation", { latestGitCheckpoints: [] }],
    [
      "a non-array conversation",
      { conversation: {}, latestGitCheckpoints: [] },
    ],
    ["missing checkpoints", { conversation }],
    ["an empty conversation", { conversation: [], latestGitCheckpoints: [] }],
  ])("rejects %s so the caller replays the log", (_case, value) => {
    expect(parseResumeSnapshot(value)).toBeNull();
  });

  it("defaults absent optional fields rather than trusting them", () => {
    const parsed = parseResumeSnapshot({
      conversation,
      latestGitCheckpoints: [],
      sessionId: 7,
    });

    expect(parsed?.sessionId).toBeNull();
    expect(parsed?.logEntryCount).toBe(0);
    expect(parsed?.latestGitCheckpoint).toBeNull();
  });
});
