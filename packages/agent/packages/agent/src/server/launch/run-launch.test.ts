import { taskRunStateSchema } from "@posthog/agent-contracts";
import { describe, expect, it } from "vitest";
import { createTask, createTaskRun } from "../../test/fixtures/api";
import type { Task, TaskRun } from "../../types";
import {
  type RunLaunchSources,
  readProductLaunch,
  readRunLaunch,
} from "./run-launch";

interface SourceOverrides
  extends Partial<Pick<RunLaunchSources, "task" | "taskRun" | "env">> {
  userId?: number;
  apiUrl?: string;
}

function sources({
  userId = 0,
  apiUrl = "https://us.posthog.com",
  ...overrides
}: SourceOverrides = {}): RunLaunchSources {
  return {
    payload: { task_id: "task-1", run_id: "run-1", user_id: userId },
    task: createTask(),
    taskRun: createTaskRun(),
    config: { apiUrl, projectId: 2 },
    env: {},
    ...overrides,
  };
}

function runWithState(state: Record<string, unknown>): TaskRun {
  return createTaskRun({ state: taskRunStateSchema.parse(state) });
}

describe("run launch", () => {
  describe("readRunLaunch", () => {
    it.each<[string, TaskRun | null, string | null]>([
      ["the recorded kind", runWithState({ snapshot_kind: "warm" }), "warm"],
      ["absent when the run has none", runWithState({}), "absent"],
      ["unknown when the run was not fetched", null, null],
    ])("reads the snapshot kind as %s", (_, taskRun, expected) => {
      expect(readRunLaunch(sources({ taskRun })).snapshotKind).toBe(expected);
    });

    it.each<[string, TaskRun | null, boolean | null]>([
      ["prewarmed", runWithState({ prewarmed: true }), true],
      ["not prewarmed", runWithState({}), false],
      ["unknown when the run was not fetched", null, null],
    ])("reads the run as %s", (_, taskRun, expected) => {
      expect(readRunLaunch(sources({ taskRun })).prewarmed).toBe(expected);
    });

    it.each<[string, number, Task | null, number | null]>([
      ["the acting user first", 7, createTask({ created_by: user(3) }), 7],
      [
        "the creator for a system run",
        0,
        createTask({ created_by: user(3) }),
        3,
      ],
      ["nobody without either", 0, null, null],
    ])("attributes the run to %s", (_, userId, task, expected) => {
      expect(readRunLaunch(sources({ userId, task })).userId).toBe(expected);
    });

    it.each<[string, Task | null, string[]]>([
      [
        "the repository list",
        createTask({ repositories: ["org/a", "org/b"], repository: "org/c" }),
        ["org/a", "org/b"],
      ],
      [
        "the legacy single repository",
        createTask({ repository: "org/c" }),
        ["org/c"],
      ],
      [
        "the legacy repository behind an empty list",
        createTask({ repositories: [], repository: "org/c" }),
        ["org/c"],
      ],
      ["no repositories without a task", null, []],
    ])("reads %s", (_, task, expected) => {
      expect(readRunLaunch(sources({ task })).repositories).toEqual(expected);
    });

    it.each<[string, Record<string, string>, string | undefined]>([
      [
        "the current variable first",
        {
          POSTHOG_CODE_INTERACTION_ORIGIN: "slack",
          CODE_INTERACTION_ORIGIN: "code",
          TWIG_INTERACTION_ORIGIN: "twig",
        },
        "slack",
      ],
      [
        "the older variables as fallbacks",
        { TWIG_INTERACTION_ORIGIN: "twig" },
        "twig",
      ],
      ["nothing when unset", {}, undefined],
    ])("reads the interaction origin from %s", (_, env, expected) => {
      expect(readRunLaunch(sources({ env })).interactionOrigin).toBe(expected);
    });

    it.each<[string, unknown, string | undefined, boolean]>([
      ["a valid prompt", "Be brief.", "Be brief.", true],
      ["a missing prompt", undefined, undefined, true],
      ["an invalid prompt", 42, undefined, false],
    ])("reads %s from the run state", (_, systemPrompt, expected, valid) => {
      const launch = readRunLaunch(
        sources({ taskRun: runWithState({ systemPrompt }) }),
      );

      expect([launch.systemPrompt, launch.systemPromptValid]).toEqual([
        expected,
        valid,
      ]);
    });
  });

  describe("readProductLaunch", () => {
    it.each<[string, Task, string | undefined]>([
      [
        "the inbox report",
        createTask({ signal_report: "rep_1" }),
        "https://us.posthog.com/project/2/inbox/rep_1",
      ],
      [
        "the web chat for a web task",
        createTask({ client_provenance: "posthog_web" }),
        "https://us.posthog.com/project/2/ai?task=task-1",
      ],
      [
        "the web chat for a browser task without provenance",
        createTask({ origin_product: "posthog_ai" }),
        "https://us.posthog.com/project/2/ai?task=task-1",
      ],
      [
        "the desktop bridge for a PostHog AI task from desktop",
        createTask({
          origin_product: "posthog_ai",
          client_provenance: "posthog_desktop",
        }),
        "https://us.posthog.com/code/task/task-1",
      ],
      [
        "the web chat for a mobile task",
        createTask({
          origin_product: "posthog_ai",
          client_provenance: "posthog_mobile",
        }),
        "https://us.posthog.com/project/2/ai?task=task-1",
      ],
      [
        "the desktop bridge for a channel task",
        createTask({ client_provenance: "posthog_desktop", channel: "ch-1" }),
        "https://us.posthog.com/code/channel/ch-1/tasks/task-1",
      ],
      [
        "the desktop bridge for a desktop task",
        createTask({ client_provenance: "posthog_desktop" }),
        "https://us.posthog.com/code/task/task-1",
      ],
      [
        "nothing for an automated task",
        createTask({ origin_product: "review_hog" }),
        undefined,
      ],
    ])("links the product source to %s", (_, task, expected) => {
      const launch = readProductLaunch(
        sources({ apiUrl: "https://us.posthog.com/", task }),
      );

      expect(launch.source?.url).toBe(expected);
    });

    it("gives products a copy of the run state", () => {
      const taskRun = runWithState({
        slack_thread_url: "https://slack/thread",
      });
      const launch = readProductLaunch(sources({ taskRun }));

      (launch.launchOptions as Record<string, unknown>).slack_thread_url =
        "changed";

      expect(taskRun.state.slack_thread_url).toBe("https://slack/thread");
    });
  });
});

function user(id: number): NonNullable<Task["created_by"]> {
  return {
    id,
    uuid: `user-${id}`,
    distinct_id: `user-${id}`,
    first_name: "Test",
    email: `user-${id}@example.com`,
  };
}
