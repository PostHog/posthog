import { describe, expect, it } from "vitest";
import { buildActivity } from "./presence-format";
import type { PresenceIntent } from "./schemas";

const STARTED_AT = 1_700_000_000_000;

const baseOptions = {
  showTaskTitle: false,
  showRepoName: false,
  startedAt: STARTED_AT,
};

const activeIntent: PresenceIntent = {
  hasActiveTask: true,
  taskTitle: "Add Discord presence",
  repoName: "posthog/code",
  agentRunning: true,
};

const idleNoTask: PresenceIntent = {
  hasActiveTask: false,
  taskTitle: null,
  repoName: null,
  agentRunning: false,
};

interface Case {
  name: string;
  intent: PresenceIntent;
  options: typeof baseOptions;
  expected: {
    details?: string;
    state?: string;
    smallImage?: string;
    smallText?: string;
    timestampStart?: number;
    detailsMaxLength?: number;
    detailsStartsWith?: string;
    detailsEndsWith?: string;
  };
}

const cases: Case[] = [
  {
    name: "hides task title and repo name by default (privacy-first)",
    intent: activeIntent,
    options: baseOptions,
    expected: { details: "Working on a task", state: "agent running" },
  },
  {
    name: "includes the task title only when opted in",
    intent: activeIntent,
    options: { ...baseOptions, showTaskTitle: true },
    expected: { details: 'Working on "Add Discord presence"' },
  },
  {
    name: "includes the repo name only when opted in",
    intent: activeIntent,
    options: { ...baseOptions, showRepoName: true },
    expected: { state: "posthog/code · agent running" },
  },
  {
    name: "shows the idle badge and review status when idle on a task",
    intent: { ...activeIntent, agentRunning: false },
    options: { ...baseOptions, showRepoName: true },
    expected: {
      state: "posthog/code · reviewing",
      smallImage: "posthog_idle",
      smallText: "Reviewing",
    },
  },
  {
    name: "falls back to idle/browsing with the idle badge when no task is focused",
    intent: idleNoTask,
    options: { ...baseOptions, showTaskTitle: true, showRepoName: true },
    expected: {
      details: "Idle",
      state: "browsing",
      smallImage: "posthog_idle",
      smallText: "Idle",
    },
  },
  {
    name: "surfaces the running indicator asset and start timestamp while working",
    intent: activeIntent,
    options: baseOptions,
    expected: { smallImage: "agent_running", timestampStart: STARTED_AT },
  },
  {
    name: "truncates over-long titles to Discord's field limit, keeping prefix and ellipsis",
    intent: { ...activeIntent, taskTitle: "x".repeat(200) },
    options: { ...baseOptions, showTaskTitle: true },
    expected: {
      detailsMaxLength: 128,
      detailsStartsWith: 'Working on "',
      detailsEndsWith: "…",
    },
  },
];

describe("buildActivity", () => {
  it.each(cases)("$name", ({ intent, options, expected }) => {
    const activity = buildActivity(intent, options);

    if (expected.details !== undefined) {
      expect(activity.details).toBe(expected.details);
    }
    if (expected.state !== undefined) {
      expect(activity.state).toBe(expected.state);
    }
    if (expected.smallImage !== undefined) {
      expect(activity.assets?.small_image).toBe(expected.smallImage);
    }
    if (expected.smallText !== undefined) {
      expect(activity.assets?.small_text).toBe(expected.smallText);
    }
    if (expected.timestampStart !== undefined) {
      expect(activity.timestamps?.start).toBe(expected.timestampStart);
    }
    if (expected.detailsMaxLength !== undefined) {
      expect(activity.details?.length).toBeLessThanOrEqual(
        expected.detailsMaxLength,
      );
    }
    if (expected.detailsStartsWith !== undefined) {
      expect(activity.details?.startsWith(expected.detailsStartsWith)).toBe(
        true,
      );
    }
    if (expected.detailsEndsWith !== undefined) {
      expect(activity.details?.endsWith(expected.detailsEndsWith)).toBe(true);
    }
  });
});
