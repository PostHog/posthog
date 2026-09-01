import type { Task } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import { selectAutofillCandidates } from "./autofill";
import { workspaceIdSet } from "./eligibility";

const NOW = new Date("2026-02-27T12:00:00Z").getTime();
const ONE_HOUR_MS = 60 * 60 * 1000;

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Task 1",
    description: "",
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    origin_product: "code",
    ...overrides,
  } as Task;
}

function candidates(opts: {
  tasks: Task[];
  workspaceIds?: string[];
  assigned?: string[];
  archived?: string[];
  emptySlots: number;
}): string[] {
  const workspaces = Object.fromEntries(
    (opts.workspaceIds ?? opts.tasks.map((t) => t.id)).map((id) => [id, {}]),
  );
  return selectAutofillCandidates(opts.tasks, {
    assignedIds: new Set(opts.assigned ?? []),
    archivedIds: new Set(opts.archived ?? []),
    workspaceIds: workspaceIdSet(workspaces),
    emptySlots: opts.emptySlots,
    nowMs: NOW,
  });
}

describe("selectAutofillCandidates", () => {
  it("returns recent tasks that have workspaces", () => {
    const result = candidates({
      tasks: [
        makeTask({ id: "t1", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "t2", updated_at: new Date(NOW - 200).toISOString() }),
      ],
      emptySlots: 4,
    });
    expect(result).toEqual(["t1", "t2"]);
  });

  it("excludes already-assigned tasks", () => {
    const result = candidates({
      tasks: [
        makeTask({ id: "t1", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "t2", updated_at: new Date(NOW - 200).toISOString() }),
      ],
      assigned: ["t1"],
      emptySlots: 4,
    });
    expect(result).toEqual(["t2"]);
  });

  it("excludes archived tasks", () => {
    const result = candidates({
      tasks: [makeTask({ id: "t1" }), makeTask({ id: "t2" })],
      archived: ["t1"],
      emptySlots: 4,
    });
    expect(result).toEqual(["t2"]);
  });

  it("excludes tasks without a workspace", () => {
    const result = candidates({
      tasks: [makeTask({ id: "t1" }), makeTask({ id: "t2" })],
      workspaceIds: ["t2"],
      emptySlots: 4,
    });
    expect(result).toEqual(["t2"]);
  });

  it("excludes tasks older than the recent window", () => {
    const result = candidates({
      tasks: [
        makeTask({
          id: "fresh",
          updated_at: new Date(NOW - 100).toISOString(),
        }),
        makeTask({
          id: "stale",
          updated_at: new Date(NOW - 3 * ONE_HOUR_MS).toISOString(),
        }),
      ],
      emptySlots: 4,
    });
    expect(result).toEqual(["fresh"]);
  });

  it("uses latest_run.updated_at when newer than task.updated_at", () => {
    const result = candidates({
      tasks: [
        makeTask({
          id: "stale",
          updated_at: new Date(NOW - 3 * ONE_HOUR_MS).toISOString(),
          latest_run: {
            id: "run-1",
            task: "stale",
            team: 1,
            branch: null,
            status: "in_progress",
            log_url: "",
            error_message: null,
            output: null,
            state: {},
            created_at: new Date(NOW - 3 * ONE_HOUR_MS).toISOString(),
            updated_at: new Date(NOW - 100).toISOString(),
            completed_at: null,
          },
        } as Task),
      ],
      emptySlots: 4,
    });
    expect(result).toEqual(["stale"]);
  });

  it("sorts by most recent activity descending", () => {
    const result = candidates({
      tasks: [
        makeTask({ id: "old", updated_at: new Date(NOW - 1000).toISOString() }),
        makeTask({ id: "new", updated_at: new Date(NOW - 100).toISOString() }),
        makeTask({ id: "mid", updated_at: new Date(NOW - 500).toISOString() }),
      ],
      emptySlots: 4,
    });
    expect(result).toEqual(["new", "mid", "old"]);
  });

  it("caps candidates at emptySlots", () => {
    const tasks = Array.from({ length: 10 }, (_, i) =>
      makeTask({ id: `t${i}`, updated_at: new Date(NOW - i).toISOString() }),
    );
    const result = candidates({ tasks, emptySlots: 4 });
    expect(result).toEqual(["t0", "t1", "t2", "t3"]);
  });

  it("returns empty when no tasks are eligible", () => {
    expect(candidates({ tasks: [], emptySlots: 4 })).toEqual([]);
  });
});
