import type { Contribution } from "@posthog/di/contribution";
import {
  HOST_TRPC_CLIENT,
  type HostTrpcClient,
} from "@posthog/host-router/client";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { inject, injectable } from "inversify";
import { track } from "../../shell/analytics";

/**
 * Boots the global agent-event listeners once at startup (formerly an inline
 * useSubscription side effect in App.tsx). Reports agent file-activity to
 * analytics so worktree write activity is tracked regardless of which view is
 * open.
 */
@injectable()
export class AgentEventsContribution implements Contribution {
  constructor(
    @inject(HOST_TRPC_CLIENT)
    private readonly hostClient: HostTrpcClient,
  ) {}

  start(): void {
    this.hostClient.agent.onAgentFileActivity.subscribe(undefined, {
      onData: (data) => {
        track(ANALYTICS_EVENTS.AGENT_FILE_ACTIVITY, {
          task_id: data.taskId,
          branch_name: data.branchName,
        });
      },
    });
  }
}
