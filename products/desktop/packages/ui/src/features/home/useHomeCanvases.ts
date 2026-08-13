import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useDashboards } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useMemo } from "react";

/**
 * How many canvases the stack renders. Each is a live sandboxed iframe, so the
 * cap is a budget as much as a layout choice — past a handful the page costs
 * more to open than it saves.
 */
export const HOME_CANVAS_LIMIT = 3;

const NO_CANVASES: DashboardRecord[] = [];

/**
 * The canvases Home stacks under its own sections: the ones pinned in your
 * personal space, oldest pin first, so the order is yours and stays put.
 *
 * Pinning is the existing signal — a canvas already carries `pinnedAt`, and the
 * canvas toolbar already sets it — so putting a canvas on Home needs no new
 * concept, and taking it off is where you'd expect.
 */
export function useHomeCanvases(options?: { enabled?: boolean }): {
  canvases: DashboardRecord[];
  personalChannelId: string | null;
  isLoading: boolean;
} {
  const enabled = options?.enabled ?? true;
  const { channels, isLoading: channelsLoading } = useChannels({ enabled });
  const personalChannelId =
    channels.find((channel) => channel.channelType === "personal")?.id ?? null;

  const { dashboards, isLoading: canvasesLoading } = useDashboards(
    enabled ? (personalChannelId ?? undefined) : undefined,
    // Home is not a live surface; polling a page of iframes off-screen is spend
    // for nothing.
    { poll: false },
  );

  const canvases = useMemo(() => {
    const pinned = dashboards.filter((canvas) => canvas.pinnedAt != null);
    if (pinned.length === 0) return NO_CANVASES;
    return [...pinned]
      .sort((a, b) => (a.pinnedAt ?? 0) - (b.pinnedAt ?? 0))
      .slice(0, HOME_CANVAS_LIMIT);
  }, [dashboards]);

  return {
    canvases,
    personalChannelId,
    isLoading: channelsLoading || (!!personalChannelId && canvasesLoading),
  };
}
