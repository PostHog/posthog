import { useChannelsLayout } from "@posthog/ui/features/canvas/hooks/useChannelsLayout";
import { useCurrentChannel } from "@posthog/ui/features/canvas/hooks/useCurrentChannel";
import {
  clearKeepListForRoute,
  shouldKeepListForRoute,
  showChannelPane,
} from "@posthog/ui/features/canvas/stores/channelPaneStore";
import { useCurrentChannelStore } from "@posthog/ui/features/canvas/stores/currentChannelStore";
import { useParams, useSearch } from "@tanstack/react-router";
import { useEffect, useRef } from "react";

/**
 * Renders nothing — owns which space the app is scoped to. Lives outside the
 * sidebar because the rail can take that column away, and the scoping still
 * has to happen.
 *
 * The scope follows the route: /spaces/:channelId anywhere in the match, or
 * the space queries the canonical task/new-task screens carry (`?from=` on
 * /tasks/:taskId, `?channel=` on /new — the pre-standardization channel path
 * segments redirect into these).
 */
export function ChannelRouteSync() {
  const channelsLayout = useChannelsLayout();
  const routeChannelId = useParams({ strict: false }).channelId;
  const taskFromChannelId = useSearch({ strict: false }).from as
    | string
    | undefined;
  const newTaskChannelId = useSearch({ strict: false }).channel as
    | string
    | undefined;
  const setCurrentChannel = useCurrentChannelStore((s) => s.setCurrentChannel);
  const { currentChannelId, channels } = useCurrentChannel({
    enabled: channelsLayout,
  });

  const scopedChannelId =
    routeChannelId ?? taskFromChannelId ?? newTaskChannelId;

  useEffect(() => {
    if (!channelsLayout) return;
    // A route with no channel ends the navigation the latch was armed for. Left
    // set, it would hold a later deep link to that channel on the list.
    if (!scopedChannelId) {
      clearKeepListForRoute();
      return;
    }
    setCurrentChannel(scopedChannelId);
    // Landing on a channel — a deep link, a mention, ⌘1-9 — is a request to see
    // it, so the slider follows the route even if the list was being browsed.
    // Unless the navigation said otherwise: opening a session from the list's
    // tree loads it without taking the tree off the screen.
    if (!shouldKeepListForRoute(scopedChannelId)) showChannelPane();
  }, [channelsLayout, scopedChannelId, setCurrentChannel]);

  const autoScopedRef = useRef(false);
  useEffect(() => {
    if (!channelsLayout) {
      autoScopedRef.current = false;
      return;
    }
    // A route-scoped channel wins over the default. Both effects run from the
    // same render on a cold deep link, so without this guard the route effect
    // writes its channel and this later effect immediately overwrites it with
    // #me using the stale `currentChannelId` captured by that render.
    if (scopedChannelId || autoScopedRef.current || currentChannelId) return;
    const me = channels.find((c) => c.channelType === "personal");
    if (!me) return;
    autoScopedRef.current = true;
    setCurrentChannel(me.id);
  }, [
    channelsLayout,
    channels,
    currentChannelId,
    scopedChannelId,
    setCurrentChannel,
  ]);

  return null;
}
