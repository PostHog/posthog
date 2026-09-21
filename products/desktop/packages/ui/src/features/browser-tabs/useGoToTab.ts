import { DEFAULT_TAB_HREF, type TabIdentity } from "@posthog/shared";
import { channelSectionFor } from "@posthog/ui/features/canvas/channelSections";
import { useChannelReportsEnabled } from "@posthog/ui/features/feature-flags/useChannelReportsEnabled";
import { useNavigate, useRouter } from "@tanstack/react-router";
import { useCallback } from "react";
import { isTabAppView } from "./tabAppViews";
import { pushTabHistoryEntry } from "./tabHistory";

export type TabRef = { id: string; href: string | null } & TabIdentity;

export function useGoToTab(): (tab: TabRef) => void {
  const navigate = useNavigate();
  const router = useRouter();
  const channelReportsEnabled = useChannelReportsEnabled();
  return useCallback(
    (tab: TabRef) => {
      const state = (prev: object) => ({ ...prev, tabId: tab.id });
      if (tab.href) {
        pushTabHistoryEntry(router.history, tab.href, tab.id);
        return;
      }
      if (tab.taskId && tab.channelId) {
        navigate({
          to: "/spaces/$channelId/tasks/$taskId",
          params: { channelId: tab.channelId, taskId: tab.taskId },
          state,
        });
      } else if (tab.taskId) {
        navigate({
          to: "/tasks/$taskId",
          params: { taskId: tab.taskId },
          state,
        });
      } else if (tab.dashboardId && tab.channelId) {
        navigate({
          to: "/spaces/$channelId/dashboards/$dashboardId",
          params: { channelId: tab.channelId, dashboardId: tab.dashboardId },
          state,
        });
      } else if (tab.channelId) {
        const params = { channelId: tab.channelId };
        const section = channelSectionFor(tab.channelSection);
        if (section) {
          navigate({
            to: `/spaces/$channelId/${section.key}` as const,
            params,
            state,
          });
        } else {
          navigate({ to: "/spaces/$channelId", params, state });
        }
      } else if (tab.appView && isTabAppView(tab.appView)) {
        switch (tab.appView) {
          case "activity":
            navigate({ to: "/activity", state });
            break;
          case "home":
          case "report":
            navigate({ to: "/", state });
            break;
          case "inbox":
            navigate({
              to: channelReportsEnabled ? "/spaces" : "/inbox",
              state,
            });
            break;
          case "agents":
            navigate({
              to: "/settings/$category",
              params: { category: "agents" },
              state,
            });
            break;
          case "loops":
            navigate({ to: "/loops", state });
            break;
          case "archived":
            navigate({ to: "/archived", state });
            break;
          case "skills":
            navigate({ to: "/skills", state });
            break;
          case "mcp-servers":
            navigate({ to: "/mcp-servers", state });
            break;
          case "command-center":
            navigate({ to: "/command-center", state });
            break;
          case "context":
            navigate({ to: "/context", search: { path: undefined }, state });
            break;
          case "settings":
            navigate({ to: "/settings", state });
            break;
          default: {
            const _exhaustive: never = tab.appView;
            return _exhaustive;
          }
        }
      } else {
        navigate({ to: DEFAULT_TAB_HREF, state });
      }
    },
    [channelReportsEnabled, navigate, router.history],
  );
}
