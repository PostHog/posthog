import type { TaskActivityItem } from "@posthog/core/canvas/taskActivity";
import type { SignalReport } from "@posthog/shared/types";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { useRouterState } from "@tanstack/react-router";

export type ActivitySelection =
  | {
      kind: "task";
      id: string;
      taskId: string;
      channelId: string | null;
    }
  | {
      kind: "report";
      id: string;
      reportId: string;
    };

/**
 * What Activity is showing beside its feed, carried in `/activity`'s search
 * params.
 *
 * It used to be a window-global store, kept out of the URL so that picking an
 * item could not route you off the feed you were reading it from. A search
 * param does not: you stay on `/activity`, the feed stays beside you. Putting it
 * in the location is what lets a tab name the session it is showing, restore it
 * on relaunch, and let two Activity tabs hold different items — none of which a
 * global store can do.
 *
 * All three fields ride along rather than resolving the item from the feed,
 * because the chrome (breadcrumb, tab label) reads them before the feed loads.
 */
export interface ActivitySearch {
  item?: string;
  session?: string;
  space?: string;
  report?: string;
}

export function parseActivitySearch(
  search: Record<string, unknown>,
): ActivitySearch {
  const str = (v: unknown) => (typeof v === "string" && v ? v : undefined);
  return {
    item: str(search.item),
    session: str(search.session),
    space: str(search.space),
    report: str(search.report),
  };
}

export function activityReportIdFromHref(href: string | null): string | null {
  if (!href) return null;
  const queryStart = href.indexOf("?");
  if (queryStart === -1) return null;
  return new URLSearchParams(href.slice(queryStart + 1)).get("report");
}

function toSelection(
  search: ActivitySearch | undefined,
): ActivitySelection | null {
  if (!search?.item) return null;
  if (search.report) {
    return {
      kind: "report",
      id: search.item,
      reportId: search.report,
    };
  }
  if (!search.session) return null;
  return {
    kind: "task",
    id: search.item,
    taskId: search.session,
    channelId: search.space ?? null,
  };
}

/** The selection, or null when nothing is picked. */
export function useActivitySelection(): ActivitySelection | null {
  return useRouterState({
    select: (s) => {
      const match = s.matches.find((m) => m.fullPath === "/activity");
      if (!match) return null;
      return toSelection(match.search as ActivitySearch);
    },
  });
}

/** Read the selection outside React (the chrome's imperative paths). */
export function getActivitySelection(): ActivitySelection | null {
  const router = getRouterOrNull();
  if (!router) return null;
  const match = router.state.matches.find((m) => m.fullPath === "/activity");
  if (!match) return null;
  return toSelection(match.search as ActivitySearch);
}

export function selectActivityItem(item: TaskActivityItem): void {
  void getRouterOrNull()?.navigate({
    to: "/activity",
    search: {
      item: item.id,
      session: item.taskId,
      ...(item.channelId ? { space: item.channelId } : {}),
    },
  });
}

export function selectActivityReport(report: SignalReport): void {
  void getRouterOrNull()?.navigate({
    to: "/activity",
    search: {
      item: report.id,
      report: report.id,
    },
  });
}
