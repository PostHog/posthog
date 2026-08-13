import type {
  HomeFiling,
  HomeNote,
  HomeProject,
  HomeStatus,
} from "@posthog/core/home/schemas";
import { homeRegistrySchema } from "@posthog/core/home/schemas";
import type { UserBasic } from "@posthog/shared/domain-types";
import { logger } from "@posthog/ui/shell/logger";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

const log = logger.scope("home-projects");

/**
 * Projects, the plans and todos they hold, and which project each session or
 * canvas is filed under.
 *
 * Filing lives here rather than on the task and canvas records because a
 * project has no backend yet: this is the reader's own arrangement of work the
 * backend already owns, the same way pinning is. That also means it is
 * per-device, and a project vanishing on another machine is expected for now.
 */
interface HomeProjectsState {
  projects: Record<string, HomeProject>;
  notes: Record<string, HomeNote>;
  /** Session or canvas id, to the project it belongs to. */
  filing: HomeFiling;

  createProject: (input: {
    spaceId: string;
    name: string;
    lead: UserBasic | null;
  }) => HomeProject;
  renameProject: (projectId: string, name: string) => void;
  setProjectStatus: (projectId: string, status: HomeStatus) => void;
  deleteProject: (projectId: string) => void;

  createNote: (input: {
    projectId: string;
    kind: HomeNote["kind"];
    title: string;
    body?: string;
    assignee: UserBasic | null;
  }) => HomeNote | null;
  updateNote: (
    noteId: string,
    patch: Partial<Pick<HomeNote, "title" | "body" | "status" | "assignee">>,
  ) => void;
  deleteNote: (noteId: string) => void;

  /** File a session or canvas under a project, or pass null to unfile it. */
  fileWork: (workId: string, projectId: string | null) => void;
}

/**
 * Everything a project's contents point back at, removed together. A note whose
 * project is gone has nowhere to render, and a filing pointing at a deleted
 * project would leave rows claiming a parent that no longer exists.
 */
function withoutProject(
  state: HomeProjectsState,
  projectId: string,
): Pick<HomeProjectsState, "projects" | "notes" | "filing"> {
  const projects = { ...state.projects };
  delete projects[projectId];
  return {
    projects,
    notes: Object.fromEntries(
      Object.entries(state.notes).filter(
        ([, note]) => note.projectId !== projectId,
      ),
    ),
    filing: Object.fromEntries(
      Object.entries(state.filing).filter(([, id]) => id !== projectId),
    ),
  };
}

export const useHomeProjectsStore = create<HomeProjectsState>()(
  persist(
    (set, get) => ({
      projects: {},
      notes: {},
      filing: {},

      createProject: ({ spaceId, name, lead }) => {
        const now = Date.now();
        const project: HomeProject = {
          id: crypto.randomUUID(),
          spaceId,
          name,
          status: "todo",
          lead,
          createdAt: now,
          updatedAt: now,
        };
        set((state) => ({
          projects: { ...state.projects, [project.id]: project },
        }));
        return project;
      },

      renameProject: (projectId, name) =>
        set((state) => {
          const project = state.projects[projectId];
          if (!project || !name.trim()) return state;
          return {
            projects: {
              ...state.projects,
              [projectId]: {
                ...project,
                name: name.trim(),
                updatedAt: Date.now(),
              },
            },
          };
        }),

      setProjectStatus: (projectId, status) =>
        set((state) => {
          const project = state.projects[projectId];
          if (!project) return state;
          return {
            projects: {
              ...state.projects,
              [projectId]: { ...project, status, updatedAt: Date.now() },
            },
          };
        }),

      deleteProject: (projectId) =>
        set((state) => withoutProject(state, projectId)),

      createNote: ({ projectId, kind, title, body = "", assignee }) => {
        if (!get().projects[projectId]) return null;
        const now = Date.now();
        const note: HomeNote = {
          id: crypto.randomUUID(),
          projectId,
          kind,
          title,
          body,
          status: "todo",
          assignee,
          createdAt: now,
          updatedAt: now,
        };
        set((state) => ({ notes: { ...state.notes, [note.id]: note } }));
        return note;
      },

      updateNote: (noteId, patch) =>
        set((state) => {
          const note = state.notes[noteId];
          if (!note) return state;
          return {
            notes: {
              ...state.notes,
              [noteId]: { ...note, ...patch, updatedAt: Date.now() },
            },
          };
        }),

      deleteNote: (noteId) =>
        set((state) => {
          const notes = { ...state.notes };
          delete notes[noteId];
          return { notes };
        }),

      fileWork: (workId, projectId) =>
        set((state) => {
          const filing = { ...state.filing };
          if (projectId) filing[workId] = projectId;
          else delete filing[workId];
          return { filing };
        }),
    }),
    {
      name: "home-projects",
      storage: electronStorage,
      partialize: ({ projects, notes, filing }) => ({
        projects,
        notes,
        filing,
      }),
      // Validate on the way in rather than trusting the file: this shape is
      // still moving, and a half-written record from an older build would
      // otherwise crash the table on every render instead of once at boot.
      merge: (persisted, current) => {
        const parsed = homeRegistrySchema.safeParse(persisted);
        if (!parsed.success) {
          if (persisted != null) {
            log.warn("Discarded unreadable saved projects", {
              issues: parsed.error.issues.length,
            });
          }
          return current;
        }
        return { ...current, ...parsed.data };
      },
    },
  ),
);
