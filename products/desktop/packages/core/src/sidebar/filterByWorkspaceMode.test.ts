import type { WorkspaceMode } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import { ALL_WORKSPACE_MODES, filterByWorkspaceMode } from "./buildSidebarData";
import type { TaskData } from "./sidebarData.types";

const task = (overrides: Partial<TaskData>): TaskData => ({
  id: "t",
  title: "t",
  createdAt: 0,
  lastActivityAt: 0,
  isGenerating: false,
  isUnread: false,
  isPinned: false,
  needsPermission: false,
  repository: null,
  isSuspended: false,
  folderPath: null,
  cloudPrUrl: null,
  branchName: null,
  linkedBranch: null,
  ...overrides,
});

describe("filterByWorkspaceMode", () => {
  const worktree = task({ id: "w", workspaceMode: "worktree" });
  const local = task({ id: "l", workspaceMode: "local" });
  const cloud = task({ id: "c", workspaceMode: "cloud" });
  const unknown = task({ id: "u", workspaceMode: undefined });
  const tasks = [worktree, local, cloud, unknown];

  it.each<{
    name: string;
    enabledModes: readonly WorkspaceMode[];
    expected: TaskData[];
  }>([
    {
      name: "returns all tasks when every mode is enabled",
      enabledModes: ALL_WORKSPACE_MODES,
      expected: tasks,
    },
    {
      name: "keeps only tasks whose mode is enabled, plus unknown-mode tasks",
      enabledModes: ["local"],
      expected: [local, unknown],
    },
    {
      name: "keeps multiple enabled modes",
      enabledModes: ["worktree", "cloud"],
      expected: [worktree, cloud, unknown],
    },
    {
      name: "keeps only unknown-mode tasks when nothing is enabled",
      enabledModes: [],
      expected: [unknown],
    },
  ])("$name", ({ enabledModes, expected }) => {
    expect(filterByWorkspaceMode(tasks, enabledModes)).toEqual(expected);
  });
});
