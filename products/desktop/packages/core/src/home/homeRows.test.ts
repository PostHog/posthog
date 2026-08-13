import type {
  Task,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import type { DashboardRecord } from "../canvas/dashboardSchemas";
import {
  buildHomeRows,
  type HomeSpaceWork,
  statusFromCanvas,
  statusFromRun,
} from "./homeRows";
import type { HomeNote, HomeProject, HomeStatus } from "./schemas";

const ADA: UserBasic = {
  id: 1,
  uuid: "ada-uuid",
  email: "ada@example.com",
  first_name: "Ada",
};

const NONE: ReadonlySet<string> = new Set();

function task(overrides: Partial<Task> = {}): Task {
  return {
    id: "task-1",
    task_number: 128,
    slug: "task-1",
    title: "Fix the export",
    description: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-02T00:00:00Z",
    created_by: ADA,
    origin_product: "user_created",
    ...overrides,
  };
}

function canvas(overrides: Partial<DashboardRecord> = {}): DashboardRecord {
  return {
    id: "canvas-1",
    channelId: "space-1",
    name: "Retention",
    templateId: "freeform",
    context: "",
    createdAt: 10,
    updatedAt: 20,
    ...overrides,
  };
}

function project(overrides: Partial<HomeProject> = {}): HomeProject {
  return {
    id: "project-1",
    spaceId: "space-1",
    name: "Onboarding",
    status: "in_progress",
    lead: null,
    createdAt: 0,
    updatedAt: 0,
    ...overrides,
  };
}

function note(overrides: Partial<HomeNote> = {}): HomeNote {
  return {
    id: "note-1",
    projectId: "project-1",
    kind: "todo",
    title: "Write the migration",
    body: "",
    status: "todo",
    assignee: null,
    createdAt: 5,
    updatedAt: 30,
    ...overrides,
  };
}

function spaceWork(overrides: Partial<HomeSpaceWork> = {}): HomeSpaceWork {
  return {
    space: { id: "space-1", name: "ux-platform", personal: false },
    tasks: [],
    canvases: [],
    ...overrides,
  };
}

type BuildInput = Parameters<typeof buildHomeRows>[0];

function build(overrides: Partial<BuildInput> = {}) {
  return buildHomeRows({
    work: [],
    projects: [],
    notes: [],
    filing: {},
    archivedTaskIds: NONE,
    pinnedTaskIds: NONE,
    ...overrides,
  });
}

describe("home rows", () => {
  it.each<[TaskRunStatus | null | undefined, HomeStatus]>([
    ["in_progress", "in_progress"],
    ["queued", "todo"],
    ["not_started", "todo"],
    ["completed", "done"],
    ["failed", "failed"],
    ["cancelled", "canceled"],
    [null, "backlog"],
    [undefined, "backlog"],
  ])("reads a %s run as %s", (runStatus, expected) => {
    expect(statusFromRun(runStatus)).toBe(expected);
  });

  it.each<[string, HomeStatus, Partial<DashboardRecord>]>([
    ["generating", "in_progress", { generationTaskId: "task-9" }],
    ["published", "done", { publishedBuildId: "build-1" }],
    ["never built", "todo", {}],
    // A canvas being regenerated is in progress even though a build is live:
    // the run in flight is the newer fact about it.
    [
      "regenerating",
      "in_progress",
      { generationTaskId: "task-9", publishedBuildId: "build-1" },
    ],
  ])("reads a %s canvas as %s", (_label, expected, overrides) => {
    expect(statusFromCanvas(canvas(overrides))).toBe(expected);
  });

  it("keeps archived sessions out of the table", () => {
    const rows = build({
      work: [
        spaceWork({
          tasks: [task({ id: "kept" }), task({ id: "archived" })],
        }),
      ],
      archivedTaskIds: new Set(["archived"]),
    });

    expect(rows.map((row) => row.id)).toEqual(["kept"]);
  });

  it("files work under the project it is filed to", () => {
    const rows = build({
      work: [
        spaceWork({ tasks: [task({ id: "filed" }), task({ id: "loose" })] }),
      ],
      projects: [project()],
      filing: { filed: "project-1" },
    });

    expect(
      Object.fromEntries(rows.map((row) => [row.id, row.projectName])),
    ).toEqual({ filed: "Onboarding", loose: null });
  });

  it("drops a filing that points at a project which no longer exists", () => {
    const rows = build({
      work: [spaceWork({ tasks: [task()] })],
      projects: [],
      filing: { "task-1": "deleted-project" },
    });

    expect(rows[0]?.projectId).toBeNull();
  });

  it("leaves out notes whose project sits outside the pinned spaces", () => {
    const rows = build({
      work: [spaceWork()],
      projects: [project({ id: "elsewhere", spaceId: "space-2" })],
      notes: [note({ projectId: "elsewhere" })],
    });

    expect(rows).toEqual([]);
  });

  it("gives a note its project's space", () => {
    const rows = build({
      work: [spaceWork()],
      projects: [project()],
      notes: [note()],
    });

    expect(rows[0]).toMatchObject({
      kind: "todo",
      spaceId: "space-1",
      spaceName: "ux-platform",
      projectName: "Onboarding",
    });
  });

  it("orders every kind together by last activity", () => {
    const rows = build({
      work: [
        spaceWork({
          tasks: [task({ id: "old", updated_at: "2026-01-01T00:00:00Z" })],
          canvases: [
            canvas({ id: "newest", updatedAt: Date.parse("2026-06-01") }),
          ],
        }),
      ],
      projects: [project()],
      notes: [note({ updatedAt: Date.parse("2026-03-01") })],
    });

    expect(rows.map((row) => row.id)).toEqual(["newest", "note-1", "old"]);
  });

  it("leaves a session that has never run unplaced rather than local", () => {
    const rows = build({ work: [spaceWork({ tasks: [task()] })] });

    expect(rows[0]?.environment).toBeNull();
  });
});
