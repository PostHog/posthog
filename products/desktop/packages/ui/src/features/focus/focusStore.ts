import {
  type EnableFocusParams,
  FocusController,
  type FocusSagaResult,
} from "@posthog/core/focus/service";
import { resolveService } from "@posthog/di/container";
import type { SagaLogger } from "@posthog/shared";
import { logger } from "@posthog/ui/shell/logger";
import type {
  FocusResult,
  FocusSession,
} from "@posthog/workspace-client/types";
import { create } from "zustand";
import { invalidateGitBranchQueries } from "../git-interaction/gitCacheKeys";
import { FOCUS_CONTROLLER_DEPS, type FocusControllerDeps } from "./focusClient";

const log = logger.scope("focus-store");

const sagaLogger: SagaLogger = {
  info: (message, data) => log.info(message, data),
  debug: (message, data) => log.debug(message, data),
  error: (message, data) => log.error(message, data),
  warn: (message, data) => log.warn(message, data),
};

let focusControllerInstance: FocusController | null = null;

function focusController(): FocusController {
  focusControllerInstance ??= new FocusController(
    resolveService<FocusControllerDeps>(FOCUS_CONTROLLER_DEPS),
    sagaLogger,
  );
  return focusControllerInstance;
}

export type { FocusSagaResult };

interface FocusState {
  session: FocusSession | null;
  isLoading: boolean;
  enableFocus: (params: EnableFocusParams) => Promise<FocusSagaResult>;
  disableFocus: () => Promise<FocusResult>;
  restore: (mainRepoPath: string) => Promise<void>;
  updateSessionBranch: (worktreePath: string, newBranch: string) => void;
}

export const useFocusStore = create<FocusState>()((set, get) => ({
  session: null,
  isLoading: false,

  enableFocus: async (params) => {
    set({ isLoading: true });
    const result = await focusController().enableFocus(params, get().session);
    set({
      isLoading: false,
      session: result.success ? result.session : get().session,
    });
    if (result.success) invalidateGitBranchQueries(params.mainRepoPath);
    return result;
  },

  disableFocus: async () => {
    const { session } = get();
    if (!session) return { success: false, error: "No active focus session" };

    set({ isLoading: true });
    const result = await focusController().disableFocus(session);
    set({ isLoading: false, session: result.success ? null : session });
    if (result.success) invalidateGitBranchQueries(session.mainRepoPath);
    return result;
  },

  restore: async (mainRepoPath) => {
    const session = await focusController().restore(mainRepoPath);
    if (session) set({ session });
  },

  updateSessionBranch: (worktreePath, newBranch) => {
    const { session } = get();
    if (session?.worktreePath === worktreePath) {
      set({ session: { ...session, branch: newBranch } });
    }
  },
}));

export const selectIsLoading = (state: FocusState) => state.isLoading;

export const selectIsFocusedOnWorktree =
  (worktreePath: string) => (state: FocusState) =>
    state.session?.worktreePath === worktreePath;
