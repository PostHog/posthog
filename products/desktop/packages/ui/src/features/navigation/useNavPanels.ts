import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { useParams, useSearch } from "@tanstack/react-router";
import { useMemo } from "react";
import {
  type NavPanelSearch,
  type RightPanelSide,
  type SecondaryPanelParam,
  type SpacePanelTab,
  validateNavPanelSearch,
} from "./navPanelSearch";

/** The chrome's panel params, validated whatever route we're on. */
export function useNavPanelSearch(): NavPanelSearch {
  const search = useSearch({ strict: false }) as Record<string, unknown>;
  return useMemo(() => validateNavPanelSearch(search), [search]);
}

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
 * panel) unless the URL pins the activity feed or closes it. Which panel shows
 * is shareable state; the panel's width is not (secondaryPanelStore).
 */
export function useSecondaryPanelState(): SecondaryPanelState {
  const search = useNavPanelSearch();
  const params = useParams({ strict: false });
  const routeChannelId = params.channelId ?? null;

  return useMemo(() => {
    const destination: SecondaryDestination | null =
      search.panel === "activity"
        ? { kind: "activity" }
        : routeChannelId
          ? { kind: "space", channelId: routeChannelId }
          : null;
    return {
      destination,
      open: destination != null && search.panel !== "off",
    };
  }, [search.panel, routeChannelId]);
}

/**
 * Go to a space's landing (or Home when null) with the panel params stripped:
 * switching destinations always opens the new one's panel fresh, whatever
 * state the previous destination left behind.
 */
export function navigateToSpaceFresh(channelId: string | null): void {
  const router = getRouterOrNull();
  if (!router) return;
  const stripPanels = (prev: Record<string, unknown>) => {
    const next = { ...prev };
    delete next.panel;
    delete next.stab;
    delete next.side;
    return next;
  };
  if (channelId) {
    void router.navigate({
      to: "/website/$channelId",
      params: { channelId },
      search: stripPanels,
    } as never);
  } else {
    void router.navigate({ to: "/website", search: stripPanels } as never);
  }
}

type NavSearchPatch = {
  panel?: SecondaryPanelParam;
  stab?: SpacePanelTab;
  side?: RightPanelSide;
};

/**
 * Patch the panel params in place. Replace-style so chrome toggles don't
 * pollute back/forward history. `null` removes a param.
 */
export function patchNavPanelSearch(
  patch: { [K in keyof NavSearchPatch]: NavSearchPatch[K] | null },
): void {
  const router = getRouterOrNull();
  if (!router) return;
  void router.navigate({
    to: ".",
    replace: true,
    search: (prev: Record<string, unknown>) => {
      const next: Record<string, unknown> = { ...prev };
      for (const [key, value] of Object.entries(patch)) {
        if (value === null) delete next[key];
        else next[key] = value;
      }
      return next;
    },
  } as never);
}
