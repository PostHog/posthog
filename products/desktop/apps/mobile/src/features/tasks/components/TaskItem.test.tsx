import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import type { Task } from "../types";
import { TaskItem } from "./TaskItem";

vi.mock("phosphor-react-native", () => ({
  Check: (props: Record<string, unknown>) => createElement("Check", props),
  GitPullRequest: (props: Record<string, unknown>) =>
    createElement("GitPullRequest", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 11: "#444444" },
    accent: { 9: "#ff5500" },
  }),
}));

vi.mock("@components/text", () => ({
  Text: (props: Record<string, unknown>) => createElement("Text", props),
}));

vi.mock("./TaskStatusIcon", () => ({
  TaskStatusIcon: (props: Record<string, unknown>) =>
    createElement("TaskStatusIcon", props),
}));

function makeTask(run?: Partial<NonNullable<Task["latest_run"]>>): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Test task",
    description: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    origin_product: "code",
    latest_run: run
      ? {
          id: "run-1",
          task: "task-1",
          team: 1,
          branch: null,
          stage: null,
          environment: "cloud",
          status: "completed",
          log_url: "",
          error_message: null,
          output: null,
          state: {},
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          completed_at: null,
          ...run,
        }
      : undefined,
  };
}

function render(task: Task) {
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(createElement(TaskItem, { task, onPress: () => {} }));
  });
  return renderer;
}

describe("TaskItem", () => {
  function prIcons(renderer: ReturnType<typeof create>) {
    return renderer.root.findAll(
      (node) => String(node.type) === "GitPullRequest",
    );
  }

  it("shows the PR badge with the parsed number when a PR url is present", () => {
    const renderer = render(
      makeTask({
        output: { pr_url: "https://github.com/PostHog/code/pull/2422" },
      }),
    );

    expect(prIcons(renderer)).toHaveLength(1);
    const number = renderer.root.findAll(
      (node) => String(node.type) === "Text" && node.props.children === "#2422",
    );
    expect(number).toHaveLength(1);
  });

  it.each([
    ["the task has no run", makeTask()],
    ["the run has no output", makeTask({ output: null })],
    [
      "the url is a GitHub issue, not a PR",
      makeTask({
        output: { pr_url: "https://github.com/PostHog/code/issues/42" },
      }),
    ],
    [
      "the url is not a GitHub url",
      makeTask({ output: { pr_url: "https://example.com/not-a-pr" } }),
    ],
  ])("does not show the PR badge when %s", (_label, task) => {
    expect(prIcons(render(task))).toHaveLength(0);
  });
});
