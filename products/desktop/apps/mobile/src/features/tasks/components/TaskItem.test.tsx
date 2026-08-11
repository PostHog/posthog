import type { Task } from "@posthog/shared";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { TaskItem } from "./TaskItem";

vi.mock("phosphor-react-native", () => ({
  Check: (props: Record<string, unknown>) => createElement("Check", props),
  GitPullRequest: (props: Record<string, unknown>) =>
    createElement("GitPullRequest", props),
  Laptop: (props: Record<string, unknown>) => createElement("Laptop", props),
  PushPin: (props: Record<string, unknown>) => createElement("PushPin", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 9: "#888888", 11: "#444444" },
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

function render(task: Task, pinned = false) {
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(
      createElement(TaskItem, { task, pinned, onPress: () => {} }),
    );
  });
  return renderer;
}

describe("TaskItem", () => {
  function prIcons(renderer: ReturnType<typeof create>) {
    return renderer.root.findAll(
      (node) => String(node.type) === "GitPullRequest",
    );
  }

  function badgeNumber(renderer: ReturnType<typeof create>, label: string) {
    return renderer.root.findAll(
      (node) => String(node.type) === "Text" && node.props.children === label,
    );
  }

  it.each([
    [
      "pr_url is set",
      { pr_url: "https://github.com/PostHog/code/pull/2422" },
      "#2422",
    ],
    [
      "pr_urls is set",
      { pr_urls: ["https://github.com/PostHog/code/pull/2422"] },
      "#2422",
    ],
    [
      "both fields point at the same PR",
      {
        pr_url: "https://github.com/PostHog/code/pull/2422",
        pr_urls: ["https://github.com/PostHog/code/pull/2422"],
      },
      "#2422",
    ],
    [
      "pr_urls lists several PRs (shows the first)",
      {
        pr_urls: [
          "https://github.com/PostHog/code/pull/2422",
          "https://github.com/PostHog/code/pull/2423",
        ],
      },
      "#2422",
    ],
  ])("shows the PR badge when %s", (_label, output, expected) => {
    const renderer = render(makeTask({ output }));

    expect(prIcons(renderer)).toHaveLength(1);
    expect(badgeNumber(renderer, expected)).toHaveLength(1);
  });

  it.each([
    ["the task has no run", makeTask()],
    ["the run has no output", makeTask({ output: null })],
    ["pr_urls is empty", makeTask({ output: { pr_urls: [] } })],
    ["pr_url is an empty string", makeTask({ output: { pr_url: "" } })],
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

  function pinIcons(renderer: ReturnType<typeof create>) {
    return renderer.root.findAll((node) => String(node.type) === "PushPin");
  }

  it.each([
    { pinned: true, expected: 1 },
    { pinned: false, expected: 0 },
  ])(
    "renders $expected pin indicator(s) when pinned is $pinned",
    ({ pinned, expected }) => {
      expect(pinIcons(render(makeTask(), pinned))).toHaveLength(expected);
    },
  );

  function laptopIcons(renderer: ReturnType<typeof create>) {
    return renderer.root.findAll((node) => String(node.type) === "Laptop");
  }

  function titleNode(renderer: ReturnType<typeof create>) {
    return renderer.root.findAll(
      (node) =>
        String(node.type) === "Text" && node.props.children === "Test task",
    )[0];
  }

  it.each([
    ["a finished desktop run", makeTask({ environment: "local" }), 1],
    [
      "a live desktop run",
      makeTask({ environment: "local", status: "in_progress" }),
      1,
    ],
    ["a cloud run", makeTask({ environment: "cloud" }), 0],
    ["no run at all", makeTask(), 0],
  ])(
    "marks %s with the right number of laptop glyphs",
    (_label, task, expected) => {
      expect(laptopIcons(render(task))).toHaveLength(expected);
    },
  );

  it("dims the title of a desktop-local task", () => {
    const local = titleNode(render(makeTask({ environment: "local" })));
    const cloud = titleNode(render(makeTask({ environment: "cloud" })));

    expect(local.props.className).toContain("text-gray-10");
    expect(cloud.props.className).toContain("text-gray-12");
  });
});
