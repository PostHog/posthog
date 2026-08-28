import type { EditorContent } from "@posthog/core/message-editor/content";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { immer } from "zustand/middleware/immer";
import type { EditorAvailableCommand } from "./types";

type SessionId = string;

export interface EditorContext {
  sessionId: string;
  taskId: string | undefined;
  repoPath: string | null | undefined;
  cloudBranch?: string | null;
  disabled: boolean;
  isLoading: boolean;
}

interface DraftState {
  drafts: Record<SessionId, EditorContent | string>;
  contexts: Record<SessionId, EditorContext>;
  commands: Record<SessionId, EditorAvailableCommand[]>;
  focusRequested: Record<SessionId, number>;
  pendingContent: Record<SessionId, EditorContent>;
  pendingInsert: Record<SessionId, EditorContent>;
  /**
   * Composer content captured when a queued-message edit begins, so cancelling
   * the edit restores the user's prior draft instead of blanking the composer.
   * Keyed by sessionId. Not persisted.
   */
  preEditDraft: Record<SessionId, EditorContent>;
  _hasHydrated: boolean;
}

export interface DraftActions {
  setHasHydrated: (hydrated: boolean) => void;
  setDraft: (sessionId: SessionId, draft: EditorContent | null) => void;
  getDraft: (sessionId: SessionId) => EditorContent | string | null;
  setContext: (
    sessionId: SessionId,
    context: Partial<Omit<EditorContext, "sessionId">>,
  ) => void;
  getContext: (sessionId: SessionId) => EditorContext | null;
  removeContext: (sessionId: SessionId) => void;
  setCommands: (
    sessionId: SessionId,
    commands: EditorAvailableCommand[],
  ) => void;
  getCommands: (sessionId: SessionId) => EditorAvailableCommand[];
  clearCommands: (sessionId: SessionId) => void;
  requestFocus: (sessionId: SessionId) => void;
  clearFocusRequest: (sessionId: SessionId) => void;
  setPendingContent: (sessionId: SessionId, content: EditorContent) => void;
  clearPendingContent: (sessionId: SessionId) => void;
  /** Insert content at the cursor (append), unlike setPendingContent which replaces. */
  insertPendingContent: (sessionId: SessionId, content: EditorContent) => void;
  clearPendingInsert: (sessionId: SessionId) => void;
  /**
   * Snapshot composer content before a queued-message edit overwrites it (see
   * {@link DraftState.preEditDraft}). Passing null clears any existing snapshot.
   */
  setPreEditDraft: (
    sessionId: SessionId,
    content: EditorContent | null,
  ) => void;
  /** Return and remove the snapshot set by {@link setPreEditDraft} (null if none). */
  takePreEditDraft: (sessionId: SessionId) => EditorContent | null;
}

type DraftStore = DraftState & { actions: DraftActions };

export const useDraftStore = create<DraftStore>()(
  persist(
    immer((set, get) => ({
      drafts: {},
      contexts: {},
      commands: {},
      focusRequested: {},
      pendingContent: {},
      pendingInsert: {},
      preEditDraft: {},
      _hasHydrated: false,

      actions: {
        setHasHydrated: (hydrated) => {
          set({ _hasHydrated: hydrated });
        },

        setDraft: (sessionId, draft) => {
          set((state) => {
            if (draft === null) {
              delete state.drafts[sessionId];
            } else {
              state.drafts[sessionId] = draft;
            }
          });
        },

        getDraft: (sessionId) => get().drafts[sessionId] ?? null,

        setContext: (sessionId, context) => {
          const existing = get().contexts[sessionId];
          const newContext: EditorContext = {
            sessionId,
            taskId: context.taskId ?? existing?.taskId,
            repoPath: context.repoPath ?? existing?.repoPath,
            cloudBranch: context.cloudBranch ?? existing?.cloudBranch,
            disabled: context.disabled ?? existing?.disabled ?? false,
            isLoading: context.isLoading ?? existing?.isLoading ?? false,
          };
          if (
            existing?.sessionId === newContext.sessionId &&
            existing?.taskId === newContext.taskId &&
            existing?.repoPath === newContext.repoPath &&
            existing?.cloudBranch === newContext.cloudBranch &&
            existing?.disabled === newContext.disabled &&
            existing?.isLoading === newContext.isLoading
          ) {
            return;
          }
          set((state) => {
            state.contexts[sessionId] = newContext;
          });
        },

        getContext: (sessionId) => get().contexts[sessionId] ?? null,

        removeContext: (sessionId) =>
          set((state) => {
            delete state.contexts[sessionId];
          }),

        setCommands: (sessionId, commands) =>
          set((state) => {
            state.commands[sessionId] = commands;
          }),

        getCommands: (sessionId) => get().commands[sessionId] ?? [],

        clearCommands: (sessionId) =>
          set((state) => {
            delete state.commands[sessionId];
          }),

        requestFocus: (sessionId) =>
          set((state) => {
            state.focusRequested[sessionId] = Date.now();
          }),

        clearFocusRequest: (sessionId) =>
          set((state) => {
            delete state.focusRequested[sessionId];
          }),

        setPendingContent: (sessionId, content) =>
          set((state) => {
            state.pendingContent[sessionId] = content;
          }),

        clearPendingContent: (sessionId) =>
          set((state) => {
            delete state.pendingContent[sessionId];
          }),

        insertPendingContent: (sessionId, content) =>
          set((state) => {
            state.pendingInsert[sessionId] = content;
          }),

        clearPendingInsert: (sessionId) =>
          set((state) => {
            delete state.pendingInsert[sessionId];
          }),

        setPreEditDraft: (sessionId, content) =>
          set((state) => {
            if (content === null) {
              delete state.preEditDraft[sessionId];
            } else {
              state.preEditDraft[sessionId] = content;
            }
          }),

        takePreEditDraft: (sessionId) => {
          const snapshot = get().preEditDraft[sessionId] ?? null;
          if (snapshot) {
            set((state) => {
              delete state.preEditDraft[sessionId];
            });
          }
          return snapshot;
        },
      },
    })),
    {
      name: "message-editor-drafts",
      storage: electronStorage,
      partialize: (state) => ({ drafts: state.drafts }),
      onRehydrateStorage: () => (state) => {
        state?.actions.setHasHydrated(true);
      },
    },
  ),
);
