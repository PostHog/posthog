import { create } from "zustand";

/** A request to open one artifact's tab once its task surface can. */
export interface PendingArtifactOpen {
  artifactId: string;
  /** Bumped per request so re-opening the same artifact applies again. */
  nonce: number;
}

interface PendingArtifactOpenStoreState {
  requestsByTask: Record<string, PendingArtifactOpen | null>;
}

interface PendingArtifactOpenStoreActions {
  requestArtifactOpen: (taskId: string, artifactId: string) => void;
  consumeArtifactOpen: (taskId: string, nonce: number) => void;
}

type PendingArtifactOpenStore = PendingArtifactOpenStoreState &
  PendingArtifactOpenStoreActions;

let nonce = 0;

/**
 * The handoff between a deep link that names an artifact and the task surface
 * that can open it. The link arrives before the task view (and its runs
 * manifest) exists, so the request is durable state a consumer takes once it
 * can resolve the artifact id to a run and a file name.
 */
export const usePendingArtifactOpenStore = create<PendingArtifactOpenStore>()(
  (set) => ({
    requestsByTask: {},

    requestArtifactOpen: (taskId, artifactId) => {
      nonce += 1;
      set((state) => ({
        requestsByTask: {
          ...state.requestsByTask,
          [taskId]: { artifactId, nonce },
        },
      }));
    },

    consumeArtifactOpen: (taskId, consumedNonce) =>
      set((state) => {
        const request = state.requestsByTask[taskId];
        if (!request || request.nonce !== consumedNonce) return state;
        return {
          requestsByTask: { ...state.requestsByTask, [taskId]: null },
        };
      }),
  }),
);
