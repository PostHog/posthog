import type { HostTrpcClient } from "@posthog/host-router/client";
import { toast } from "@posthog/ui/primitives/toast";
import { navigateToChannelDashboard } from "@posthog/ui/router/navigationBridge";
import { logger } from "@posthog/ui/shell/logger";

const log = logger.scope("fork-canvas");

/**
 * Copy a canvas into the caller's personal space and open the copy. The
 * "link to a copy" form of a canvas link lands here, so the opener never
 * edits the shared original by accident.
 */
export async function forkCanvasAndOpen(
  client: HostTrpcClient,
  dashboardId: string,
): Promise<void> {
  try {
    const copy = await client.dashboards.fork.mutate({ id: dashboardId });
    toast.success("Copied to your personal space", {
      description: "Edits here won't change the original canvas.",
    });
    navigateToChannelDashboard(copy.channelId, copy.id);
  } catch (error) {
    log.error("Failed to copy canvas", { dashboardId, error: String(error) });
    toast.error("Couldn't copy this canvas", {
      description: error instanceof Error ? error.message : String(error),
    });
  }
}

// The click interceptor for in-app links has no tRPC client of its own, so the
// deep-link hook (which does) registers the fork here and the interceptor asks
// for it by canvas id.
let forkHandler: ((dashboardId: string) => void) | null = null;

export function setForkCanvasHandler(
  handler: ((dashboardId: string) => void) | null,
): void {
  forkHandler = handler;
}

export function requestCanvasFork(dashboardId: string): boolean {
  if (!forkHandler) return false;
  forkHandler(dashboardId);
  return true;
}
