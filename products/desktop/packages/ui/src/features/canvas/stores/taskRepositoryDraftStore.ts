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
  /** Drop a consumed draft so the next task starts from the space defaults again. */
  clearDraft: (channelId: string) => void;
}

// The next-task repository selection for each space. Held outside the
// composers so a pick made on one surface (space home, new-task screen)
// survives navigation and shows on the others, the way the prompt draft does.
// Like the prompt draft, it lives until the task it was picked for is created;
// the dialog's "save to space" checkbox is the durable path.
export const useTaskRepositoryDraftStore = create<TaskRepositoryDraftState>()(
  (set) => ({
    drafts: {},
    setDraft: (channelId, draft) =>
      set((state) => ({ drafts: { ...state.drafts, [channelId]: draft } })),
    clearDraft: (channelId) =>
      set((state) => {
        if (!(channelId in state.drafts)) {
          return state;
        }
        const { [channelId]: _dropped, ...drafts } = state.drafts;
        return { drafts };
      }),
  }),
);

/**
 * Rebind repositories only when the current project has one unambiguous
 * integration. The backend still verifies that it can access every repository.
 */
export function resolveTaskRepositoryDraft(
  draft: TaskRepositoryDraft | undefined,
  channelRepositories: string[],
  channelGithubIntegration: number | null,
  availableGithubIntegrationIds: number[] = [],
): TaskRepositoryDraft {
  const selection = draft ?? {
    repositories: channelRepositories,
    githubIntegration: channelGithubIntegration,
    folder: "",
  };
  const availableGithubIntegrationId =
    availableGithubIntegrationIds.length === 1
      ? availableGithubIntegrationIds[0]
      : undefined;

  if (
    selection.repositories.length === 0 ||
    selection.githubIntegration !== null ||
    availableGithubIntegrationId === undefined
  ) {
    return selection;
  }

  return {
    ...selection,
    githubIntegration: availableGithubIntegrationId,
  };
}
