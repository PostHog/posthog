import {
  electronStorage,
  flushRendererStateWrites,
} from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface LoopBuilderSession {
  taskId: string;
  prompt: string;
  startedAt: number;
  /** Auth identity (`getAuthIdentity`) the session belongs to. Sessions are
   * only shown, pruned and capped within their own identity, so prompts never
   * leak across accounts or projects sharing a device. */
  identity: string;
}

export const MAX_BUILDER_SESSIONS = 5;

interface LoopBuilderSessionState {
  sessions: LoopBuilderSession[];
  // Hydration is async (Electron storage over IPC); readers that must not
  // mistake "not loaded yet" for "no sessions" wait on this flag.
  _hasHydrated: boolean;
  addSession: (session: LoopBuilderSession) => void;
  removeSession: (taskId: string) => void;
  setHasHydrated: (hydrated: boolean) => void;
}

export const useLoopBuilderSessionStore = create<LoopBuilderSessionState>()(
  persist(
    (set) => ({
      sessions: [],
      _hasHydrated: false,
      // Flushed immediately: adding is followed by navigating away, and a lost
      // debounced write is exactly the "can't find my builder" bug again.
      addSession: (session) => {
        set((state) => {
          const others = state.sessions.filter(
            (s) => s.identity !== session.identity,
          );
          const mine = [
            session,
            ...state.sessions.filter(
              (s) =>
                s.identity === session.identity && s.taskId !== session.taskId,
            ),
          ].slice(0, MAX_BUILDER_SESSIONS);
          return { sessions: [...mine, ...others] };
        });
        void flushRendererStateWrites();
      },
      removeSession: (taskId) => {
        set((state) => ({
          sessions: state.sessions.filter((s) => s.taskId !== taskId),
        }));
        void flushRendererStateWrites();
      },
      setHasHydrated: (hydrated) => set({ _hasHydrated: hydrated }),
    }),
    {
      name: "posthog-code-loop-builder-sessions",
      storage: electronStorage,
      partialize: (state) => ({ sessions: state.sessions }),
      // v0 entries had no identity and can't be attributed; drop them.
      version: 1,
      migrate: () => ({ sessions: [] as LoopBuilderSession[] }),
      onRehydrateStorage: () => (state) => {
        if (state) {
          state.setHasHydrated(true);
          return;
        }
        useLoopBuilderSessionStore.setState({ _hasHydrated: true });
      },
    },
  ),
);
