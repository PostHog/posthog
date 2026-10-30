import type { Task } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { statusChips } from "./status";

const task = (
  run: Record<string, unknown> | undefined,
  repository = "posthog/posthog",
): Task => ({ id: "t", repository, latest_run: run }) as unknown as Task;

describe("statusChips", () => {
  it.each([
    [
      "a cloud run with a draft PR",
      task({
        environment: "cloud",
        pr_url: "https://github.com/PostHog/posthog/pull/108476",
        pr_state: "draft",
      }),
      [
        { label: "Cloud" },
        { label: "posthog" },
        {
          label: "Draft #108476",
          url: "https://github.com/PostHog/posthog/pull/108476",
          tone: "draft",
        },
      ],
    ],
    [
      "a merged PR found only in the run's output",
      task({
        environment: "cloud",
        output: { pr_url: "https://github.com/PostHog/posthog/pull/9" },
        pr_state: "merged",
      }),
      [
        { label: "Cloud" },
        { label: "posthog" },
        {
          label: "Merged #9",
          url: "https://github.com/PostHog/posthog/pull/9",
          tone: "merged",
        },
      ],
    ],
    [
      "a local run without a PR",
      task({ environment: "local" }),
      [{ label: "Local" }, { label: "posthog" }],
    ],
  ])("for %s", (_, subject, chips) => {
    expect(statusChips(subject, null)).toEqual(chips);
  });

  it.each([
    ["cloud", "Cloud"],
    ["local", "Local"],
  ] as const)(
    "describes a %s chat without a server task by where it runs",
    (place, label) => {
      expect(statusChips(undefined, "PostHog/posthog-js", place)).toEqual([
        { label },
        { label: "posthog-js" },
      ]);
    },
  );
});
