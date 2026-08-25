import { useChannelsWorld } from "@posthog/ui/features/canvas/hooks/useChannelsWorld";
import { useRouterState } from "@tanstack/react-router";

/**
 * Whether `ShellLayout` is drawing the in-pane header for the current route.
 *
 * The root mounts the shared `ContentHeader` everywhere this is false, so the
 * two have to answer from the same rule or a route gets two headers or none.
 *
 * Read off the match chain rather than the path: `_shell` is pathless, so the
 * URL no longer says which routes it covers.
 */
export function useShellOwnsHeader(): boolean {
  const channelsWorld = useChannelsWorld();
  const inShell = useRouterState({
    select: (s) => s.matches.some((m) => m.routeId.startsWith("/_shell")),
  });
  return inShell && channelsWorld;
}
