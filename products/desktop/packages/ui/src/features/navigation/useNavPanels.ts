import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { useParams } from "@tanstack/react-router";
import { useMemo } from "react";
import { useNavPanelStore } from "./navPanelStore";

export type SecondaryDestination =
  | { kind: "activity" }
  | { kind: "space"; channelId: string };

export interface SecondaryPanelState {
  /** What the panel would show. Null on views without one (Home, Inbox, …). */
  destination: SecondaryDestination | null;
  /** Whether the panel column is open (destination present and not closed). */
  open: boolean;
}

/**
 * The secondary panel follows the route (a space route shows that space's
 * panel) unless the chrome pins the activity feed or closes it. Off a space
 * route it holds the space it was last showing, so following something out of
 * a space — a loop opens under /code — doesn't close the column.
 */
export function useSecondaryPanelState(): SecondaryPanelState {
  const panel = useNavPanelStore((s) => s.panel);
  const spaceId = useNavPanelStore((s) => s.spaceId);
  const params = useParams({ strict: false });
  const channelId = params.channelId ?? spaceId;

  return useMemo(() => {
    const destination: SecondaryDestination | null =
      panel === "activity"
        ? { kind: "activity" }
        : channelId
          ? { kind: "space", channelId }
          : null;
    return {
      destination,
      open: destination != null && panel !== "off",
    };
  }, [panel, channelId]);
}

/**
 * Go to a space's landing (or Home when null) with the panel state back at its
 * defaults: switching destinations always opens the new one's panel fresh,
 * whatever state the previous destination left behind.
 */
export function navigateToSpaceFresh(channelId: string | null): void {
  const router = getRouterOrNull();
  if (!router) return;
  useNavPanelStore.getState().reset();
  if (channelId) {
    void router.navigate({
      to: "/website/$channelId",
      params: { channelId },
    } as never);
  } else {
    void router.navigate({ to: "/website" } as never);
  }
}
