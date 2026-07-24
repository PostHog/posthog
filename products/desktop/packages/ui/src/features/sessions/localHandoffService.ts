import type {
  LocalHandoffDialog,
  LocalHandoffNotifier,
  LocalHandoffPending,
} from "@posthog/core/sessions/localHandoffService";
import { useHandoffDialogStore } from "@posthog/ui/features/sessions/handoffDialogStore";
import { toast } from "@posthog/ui/primitives/toast";
import { logger } from "@posthog/ui/shell/logger";

export type {
  LocalHandoffDialog,
  LocalHandoffHost,
  LocalHandoffNotifier,
  LocalHandoffPending,
} from "@posthog/core/sessions/localHandoffService";
export {
  LOCAL_HANDOFF_DIALOG,
  LOCAL_HANDOFF_HOST,
  LOCAL_HANDOFF_NOTIFIER,
  LOCAL_HANDOFF_SERVICE,
  LocalHandoffService,
} from "@posthog/core/sessions/localHandoffService";

const log = logger.scope("local-handoff-service");

export const localHandoffDialog: LocalHandoffDialog = {
  openConfirm: (taskId, branchName) =>
    useHandoffDialogStore
      .getState()
      .openConfirm(taskId, "to-local", branchName),
  closeConfirm: () => useHandoffDialogStore.getState().closeConfirm(),
  cancelPendingFlow: () =>
    useHandoffDialogStore.getState().cancelPendingHandoff(),
  hideDirtyTree: () => useHandoffDialogStore.getState().hideDirtyTree(),
  getPendingAfterCommit: (): LocalHandoffPending | null =>
    useHandoffDialogStore.getState().pendingAfterCommit,
  clearPendingAfterCommit: () =>
    useHandoffDialogStore.getState().clearPendingAfterCommit(),
  openDirtyTreeForPendingHandoff: (changedFiles, pending) =>
    useHandoffDialogStore
      .getState()
      .openDirtyTreeForPendingHandoff(
        changedFiles as Parameters<
          ReturnType<
            typeof useHandoffDialogStore.getState
          >["openDirtyTreeForPendingHandoff"]
        >[0],
        pending,
      ),
};

export const localHandoffNotifier: LocalHandoffNotifier = {
  error: (message) => toast.error(message),
  warn: (message, data) => log.warn(message, data),
  logError: (message, data) => log.error(message, data),
};
