import { create } from "zustand";

/** A task-level repository/folder pick made in a composer's repository dialog. */
export interface TaskRepositoryDraft {
  repositories: string[];
  githubIntegration: number | null;
  folder: string;
}

interface TaskRepositoryDraftState {
  /** Keyed by backend channel UUID, so every composer in a space shares one draft. */
  drafts: Record<string, TaskRepositoryDraft>;
  setDraft: (channelId: string, draft: TaskRepositoryDraft) => void;
}

// The next-task repository selection for each space. Held outside the
// composers so a pick made on one surface (space home, new-task screen)
// survives navigation and shows on the others, the way the prompt draft does.
export const useTaskRepositoryDraftStore = create<TaskRepositoryDraftState>()(
  (set) => ({
    drafts: {},
    setDraft: (channelId, draft) =>
      set((state) => ({ drafts: { ...state.drafts, [channelId]: draft } })),
  }),
);

/**
 * The selection a composer should show: the space draft when one exists,
 * otherwise the space's saved defaults. An existing draft wins wholesale —
 * an emptied repository list or cleared integration is a deliberate pick,
 * not a gap to backfill from the defaults.
 */
export function resolveTaskRepositoryDraft(
  draft: TaskRepositoryDraft | undefined,
  channelRepositories: string[],
  channelGithubIntegration: number | null,
): TaskRepositoryDraft {
  if (draft) {
    return draft;
  }
  return {
    repositories: channelRepositories,
    githubIntegration: channelGithubIntegration,
    folder: "",
  };
}
