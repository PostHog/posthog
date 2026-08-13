import type {
  Task,
  TaskRunStatus,
  UserBasic,
} from "@posthog/shared/domain-types";
import type { DashboardRecord } from "../canvas/dashboardSchemas";
import type {
  HomeFiling,
  HomeNote,
  HomeProject,
  HomeStatus,
  HomeWorkKind,
} from "./schemas";

/** A space, trimmed to what the home table names it by. */
export interface HomeSpace {
  id: string;
  name: string;
  /** The private `#me` space, which reads differently from a shared one. */
  personal: boolean;
}

/** One pinned space and the work the app already knows it holds. */
export interface HomeSpaceWork {
  space: HomeSpace;
  tasks: readonly Task[];
  canvases: readonly DashboardRecord[];
}

/**
 * One line of the home table. Every kind of work flattens to this, so the table
 * sorts, groups and filters over a single shape rather than branching per kind
 * in the renderer.
 */
export interface HomeRow {
  /** Unique across kinds — an id alone can collide between a note and a task. */
  key: string;
  kind: HomeWorkKind;
  id: string;
  title: string;
  status: HomeStatus;
  /** The dim leading label, e.g. a session's `#128`. Null when it has none. */
  reference: string | null;
  spaceId: string;
  spaceName: string;
  projectId: string | null;
  projectName: string | null;
  /**
   * Who the work belongs to. For a session that is whoever started it — the
   * agent runs on their behalf, so there is no second person to name.
   */
  assignee: UserBasic | null;
  createdAt: number;
  updatedAt: number;
  pinned: boolean;
  /** Where a session runs. Null for the kinds that don't run. */
  environment: "local" | "cloud" | null;
  /** The product that filed the session, when it wasn't started here. */
  source: string | null;
  /**
   * The task behind a `session` row, null for every other kind. Rows need the
   * whole record rather than a projection: opening a session hands it to the
   * navigation seam, which provisions its workspace from fields the row itself
   * has no reason to carry.
   */
  task: Task | null;
}

/**
 * `origin_product` for a session started here rather than filed by another
 * product. It's the default the backend stamps on, so it means "no source".
 */
const SELF_ORIGIN = "user_created";

/**
 * A run's status in the table's vocabulary. A session with no run at all has
 * been written but never started, which is exactly what backlog means.
 */
export function statusFromRun(
  status: TaskRunStatus | null | undefined,
): HomeStatus {
  switch (status) {
    case "in_progress":
      return "in_progress";
    case "queued":
    case "not_started":
      return "todo";
    case "completed":
      return "done";
    case "failed":
      return "failed";
    case "cancelled":
      return "canceled";
    default:
      return "backlog";
  }
}

/**
 * A canvas's status is read off its build lifecycle rather than stored: a
 * canvas being generated is in progress, one with a live build is finished
 * work, and one that has never built is a name somebody reserved.
 */
export function statusFromCanvas(canvas: DashboardRecord): HomeStatus {
  if (canvas.generationTaskId) return "in_progress";
  return canvas.publishedBuildId ? "done" : "todo";
}

function taskReference(task: Task): string | null {
  return task.task_number == null ? null : `#${task.task_number}`;
}

function rowFromTask(
  task: Task,
  space: HomeSpace,
  project: HomeProject | null,
  pinnedTaskIds: ReadonlySet<string>,
): HomeRow {
  return {
    key: `session:${task.id}`,
    kind: "session",
    id: task.id,
    title: task.title || "Untitled session",
    status: statusFromRun(task.latest_run?.status),
    reference: taskReference(task),
    spaceId: space.id,
    spaceName: space.name,
    projectId: project?.id ?? null,
    projectName: project?.name ?? null,
    assignee: task.created_by ?? null,
    createdAt: Date.parse(task.created_at) || 0,
    updatedAt: Date.parse(task.updated_at) || 0,
    pinned: pinnedTaskIds.has(task.id),
    // A session that has never run is unplaced, not local: claiming a machine
    // for it would put it under a filter it can't actually satisfy.
    environment: task.latest_run
      ? task.latest_run.environment === "cloud"
        ? "cloud"
        : "local"
      : null,
    source:
      task.origin_product && task.origin_product !== SELF_ORIGIN
        ? task.origin_product
        : null,
    task,
  };
}

function rowFromCanvas(
  canvas: DashboardRecord,
  space: HomeSpace,
  project: HomeProject | null,
): HomeRow {
  return {
    key: `canvas:${canvas.id}`,
    kind: "canvas",
    id: canvas.id,
    title: canvas.name,
    status: statusFromCanvas(canvas),
    reference: null,
    spaceId: space.id,
    spaceName: space.name,
    projectId: project?.id ?? null,
    projectName: project?.name ?? null,
    // A canvas record carries only its author's name and uuid, so the avatar
    // gets what it needs and nothing that would claim more than we know.
    assignee: canvas.createdByUuid
      ? {
          id: 0,
          uuid: canvas.createdByUuid,
          email: "",
          first_name: canvas.createdBy ?? "",
        }
      : null,
    createdAt: canvas.createdAt,
    updatedAt: canvas.updatedAt,
    pinned: canvas.pinnedAt != null,
    environment: null,
    source: null,
    task: null,
  };
}

function rowFromNote(
  note: HomeNote,
  project: HomeProject,
  space: HomeSpace,
): HomeRow {
  return {
    key: `${note.kind}:${note.id}`,
    kind: note.kind,
    id: note.id,
    title: note.title || (note.kind === "plan" ? "Untitled plan" : "Untitled"),
    status: note.status,
    reference: null,
    spaceId: space.id,
    spaceName: space.name,
    projectId: project.id,
    projectName: project.name,
    assignee: note.assignee,
    createdAt: note.createdAt,
    updatedAt: note.updatedAt,
    pinned: false,
    environment: null,
    source: null,
    task: null,
  };
}

/**
 * Every piece of work across the pinned spaces, newest activity first.
 *
 * Notes are keyed off their project rather than a space, so a plan whose
 * project sits in an unpinned space stays out — the table's promise is that it
 * shows the pinned spaces and nothing else, and a project is only ever in one.
 */
export function buildHomeRows({
  work,
  projects,
  notes,
  filing,
  archivedTaskIds,
  pinnedTaskIds,
}: {
  work: readonly HomeSpaceWork[];
  projects: readonly HomeProject[];
  notes: readonly HomeNote[];
  filing: HomeFiling;
  archivedTaskIds: ReadonlySet<string>;
  pinnedTaskIds: ReadonlySet<string>;
}): HomeRow[] {
  const projectById = new Map(projects.map((project) => [project.id, project]));
  const spaceById = new Map(work.map(({ space }) => [space.id, space]));
  const projectFor = (workId: string): HomeProject | null => {
    const projectId = filing[workId];
    return projectId ? (projectById.get(projectId) ?? null) : null;
  };

  const rows: HomeRow[] = [];

  for (const { space, tasks, canvases } of work) {
    for (const task of tasks) {
      if (archivedTaskIds.has(task.id)) continue;
      rows.push(rowFromTask(task, space, projectFor(task.id), pinnedTaskIds));
    }
    for (const canvas of canvases) {
      rows.push(rowFromCanvas(canvas, space, projectFor(canvas.id)));
    }
  }

  for (const note of notes) {
    const project = projectById.get(note.projectId);
    const space = project ? spaceById.get(project.spaceId) : undefined;
    if (!project || !space) continue;
    rows.push(rowFromNote(note, project, space));
  }

  return rows.sort((a, b) => b.updatedAt - a.updatedAt);
}
