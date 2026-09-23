import {
  type CanvasNavIntent,
  canvasConnectorProviderSchema,
} from "@posthog/core/canvas/freeformSchemas";
import { useCreateAndOpenDashboard } from "@posthog/ui/features/canvas/hooks/useDashboards";
import type { SettingsCategory } from "@posthog/ui/features/settings/types";
import {
  navigateToChannelDashboard,
  navigateToChannelTask,
  navigateToSettings,
} from "@posthog/ui/router/navigationBridge";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { useCallback } from "react";

/** The settings page where a viewer connects a connector provider. */
export function connectorSettingsCategory(
  provider: string,
): SettingsCategory | null {
  if (!canvasConnectorProviderSchema.safeParse(provider).success) return null;
  return provider === "github" ? "github" : "mcp-servers";
}

/**
 * Routes a canvas's allowlisted nav intent to real host navigation. channelId is
 * host-supplied (never from the iframe), so the canvas can only move within its
 * own channel. The returned callback switches exhaustively over the intent union.
 */
export function useCanvasNavigation(
  channelId: string,
): (intent: CanvasNavIntent) => void {
  const createAndOpen = useCreateAndOpenDashboard(channelId);
  return useCallback(
    (intent: CanvasNavIntent) => {
      switch (intent.target) {
        case "task":
          navigateToChannelTask(channelId, intent.taskId);
          break;
        case "new-task":
          // Via openTaskInput so a stale prefill can't leak into the composer.
          openTaskInput({ channelId });
          break;
        case "compose-task":
          openTaskInput({
            channelId,
            initialPrompt: intent.prompt,
            initialCloudRepository: intent.repository,
            newTab: true,
          });
          break;
        case "canvas":
          navigateToChannelDashboard(channelId, intent.dashboardId);
          break;
        case "new-canvas":
          void createAndOpen();
          break;
        case "connect": {
          const category = connectorSettingsCategory(intent.provider);
          if (category) navigateToSettings(category);
          break;
        }
      }
    },
    [channelId, createAndOpen],
  );
}
