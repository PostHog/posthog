import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { inject, injectable } from "inversify";
import { logger } from "../../shell/logger";
import {
  IMPERATIVE_QUERY_CLIENT,
  type ImperativeQueryClient,
} from "../../shell/queryClient";
import { toastError } from "../notifications/errorDetails";
import { WORKSPACE_QUERY_KEY } from "../workspace/identifiers";
import { useFocusStore } from "./focusStore";

const log = logger.scope("focus-events");

/**
 * Boots the global focus-event listeners once at startup (formerly inline
 * useSubscription side effects in App.tsx). A host-side branch rename keeps the
 * focus session's branch in sync and refreshes the workspace query; a foreign
 * branch checkout out from under a focused worktree auto-unfocuses.
 */
@injectable()
export class FocusEventsContribution implements Contribution {
  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
    @inject(IMPERATIVE_QUERY_CLIENT)
    private readonly queryClient: ImperativeQueryClient,
  ) {}

  start(): void {
    this.hostClient.focus.onBranchRenamed.subscribe(undefined, {
      onData: ({ worktreePath, newBranch }) => {
        useFocusStore.getState().updateSessionBranch(worktreePath, newBranch);
        void this.queryClient.invalidateQueries({
          queryKey: WORKSPACE_QUERY_KEY,
        });
      },
    });

    this.hostClient.focus.onForeignBranchCheckout.subscribe(undefined, {
      onData: async ({ focusedBranch, foreignBranch }) => {
        log.warn(
          `Foreign branch checkout detected: ${focusedBranch} -> ${foreignBranch}. Auto-unfocusing.`,
        );
        const result = await useFocusStore.getState().disableFocus();
        if (!result.success && result.error) {
          toastError("Could not unfocus workspace", result.error);
        }
      },
    });
  }
}
