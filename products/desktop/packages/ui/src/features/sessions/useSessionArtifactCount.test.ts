import type { TaskRunArtifact } from "@posthog/shared";
import {
  countArtifacts,
  isAgentWorking,
} from "@posthog/ui/features/sessions/useSessionArtifactCount";
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

describe("countArtifacts", () => {
  const file = (name: string): TaskRunArtifact => ({ name, type: "output" });
  const pr = (n: number): string => `https://github.com/acme/app/pull/${n}`;

  it.each([
    {
      // The regression: a PR the run just opened is in the session's live
      // output before the task query refetches, so counting the task alone
      // misses it at the turn boundary.
      name: "counts a PR only present in the session's live output",
      manifest: [] as TaskRunArtifact[],
      taskOutput: null,
      cloudOutput: { pr_urls: [pr(1)] },
      expected: 1,
    },
    {
      name: "counts a PR only present in the task output",
      manifest: [] as TaskRunArtifact[],
      taskOutput: { pr_urls: [pr(1)] },
      cloudOutput: null,
      expected: 1,
    },
    {
      name: "counts a PR in both outputs once",
      manifest: [] as TaskRunArtifact[],
      taskOutput: { pr_urls: [pr(1)] },
      cloudOutput: { pr_url: pr(1) },
      expected: 1,
    },
    {
      name: "counts distinct PRs across both outputs",
      manifest: [] as TaskRunArtifact[],
      taskOutput: { pr_urls: [pr(1)] },
      cloudOutput: { pr_urls: [pr(2)] },
      expected: 2,
    },
    {
      name: "adds undismissed output files to the PR count",
      manifest: [file("report.csv")],
      taskOutput: { pr_urls: [pr(1)] },
      cloudOutput: null,
      expected: 2,
    },
    {
      name: "adds PostHog references to the artifact count",
      manifest: [
        {
          id: "phref-1",
          name: "Checkout funnel",
          type: "reference" as const,
          source: "posthog_object" as const,
          metadata: {
            reference_type: "posthog_object" as const,
            object_kind: "insight",
            object_id: "9pQx3",
            source_message_ids: ["turn-1"],
            occurrence_count: 1,
          },
        },
      ],
      taskOutput: null,
      cloudOutput: null,
      expected: 1,
    },
  ])("$name", ({ manifest, taskOutput, cloudOutput, expected }) => {
    expect(countArtifacts({ manifest, taskOutput, cloudOutput })).toBe(
      expected,
    );
  });
});
