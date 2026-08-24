import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { railPaneForMatches } from "@posthog/ui/features/canvas/railPane";
import { useChannelPaneStore } from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useRailHistoryStore } from "@posthog/ui/features/canvas/stores/railHistoryStore";
import { useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

/**
 * Renders nothing — records where each rail destination was when you left it.
 *
 * One writer, on every settled navigation, rather than a note the rail takes as
 * you click away: a destination is also left by hotkeys, deep links and links
 * in the content, and a pick that only remembered its own departures would
 * return you somewhere you had already moved on from.
 */
export function RailHistorySync() {
  const channelsLayout = useChannelsLayout();
  // Destination, href and space each read off the router snapshot. They settle
  // together, so three selectors cannot disagree within a render.
  //
  // `resolvedLocation`, not `location`: during a pending navigation `location`
  // is already the destination while `matches` still describes the page being
  // left, and that pair records the old destination against the new href — so
  // every pick sends you to the page you were walking away from.
  const pane = useRouterState({ select: (s) => railPaneForMatches(s.matches) });
  const href = useRouterState({
    select: (s) => (s.resolvedLocation ?? s.location).href,
  });
  const spaceId = useRouterState({
    select: (s) =>
      (
        s.matches[s.matches.length - 1]?.params as
          | { channelId?: string }
          | undefined
      )?.channelId,
  });
  const listOpen = useChannelPaneStore((s) => s.pane === "list");
  const record = useRailHistoryStore((s) => s.record);

  useEffect(() => {
    if (!channelsLayout) return;
    record(pane, {
      href,
      spaces: pane === "spaces" ? { listOpen, spaceId } : undefined,
    });
  }, [channelsLayout, pane, href, spaceId, listOpen, record]);

  return null;
}
