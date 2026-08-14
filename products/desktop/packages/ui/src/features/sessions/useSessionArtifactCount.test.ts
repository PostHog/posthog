import { isAgentWorking } from "@posthog/ui/features/sessions/useSessionArtifactCount";
import { describe, expect, it } from "vitest";

describe("isAgentWorking", () => {
  it.each([
    {
      name: "a turn in flight in this window",
      hasSession: true,
      isPromptPending: true,
      runStatus: "in_progress",
      expected: true,
    },
    // The one that bit: a cloud run stays in_progress across every turn until
    // the whole run ends, so reading its status kept the between-turns moment
    // shut for the length of the session.
    {
      name: "between turns of a cloud run that is still alive",
      hasSession: true,
      isPromptPending: false,
      runStatus: "in_progress",
      expected: false,
    },
    {
      name: "a run this window only watches",
      hasSession: false,
      isPromptPending: false,
      runStatus: "in_progress",
      expected: true,
    },
    {
      name: "a finished run nobody is driving",
      hasSession: false,
      isPromptPending: false,
      runStatus: "completed",
      expected: false,
    },
  ])("$name", ({ hasSession, isPromptPending, runStatus, expected }) => {
    expect(isAgentWorking({ hasSession, isPromptPending, runStatus })).toBe(
      expected,
    );
  });
});
