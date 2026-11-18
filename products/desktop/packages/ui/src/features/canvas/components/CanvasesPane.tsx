import {
  type CanvasListService,
  type CanvasListSettings,
  DEFAULT_CANVAS_LIST_SETTINGS,
} from "@posthog/core/canvas/canvasListService";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { CANVAS_LIST_SERVICE } from "@posthog/core/canvas/identifiers";
import { useService } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { CanvasFilterMenu } from "@posthog/ui/features/canvas/components/CanvasFilterMenu";
import { buildCanvasSpaceOptions } from "@posthog/ui/features/canvas/components/canvasSpaceOptions";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useSelectedCanvasId } from "@posthog/ui/features/canvas/hooks/useSelectedCanvasId";
import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate } from "@tanstack/react-router";
import { type ReactElement, useEffect, useMemo, useState } from "react";
import { CanvasList } from "./CanvasList";

export function CanvasesPane({
  className,
}: {
  className?: string;
}): ReactElement {
  const { dashboards, isLoading } = useAllCanvases();
  const { channels } = useChannels();
  const { data: currentUser } = useMeQuery();
  const canvasListService = useService<CanvasListService>(CANVAS_LIST_SERVICE);
  const navigate = useNavigate();
  const selectedId = useSelectedCanvasId();
  const [query, setQuery] = useState("");
  const [settings, setSettings] = useState<CanvasListSettings>(
    DEFAULT_CANVAS_LIST_SETTINGS,
  );
  const [recentlyViewedSortSnapshot, setRecentlyViewedSortSnapshot] = useState<
    Record<string, number>
  >(() => ({ ...useCanvasViewedStore.getState().lastViewedAtByCanvasId }));
  const lastViewedAtByCanvasId = useCanvasViewedStore(
    (state) => state.lastViewedAtByCanvasId,
  );
  useEffect(() => {
    if (useCanvasViewedStore.persist.hasHydrated()) {
      setRecentlyViewedSortSnapshot({
        ...useCanvasViewedStore.getState().lastViewedAtByCanvasId,
      });
      return;
    }
    return useCanvasViewedStore.persist.onFinishHydration((state) => {
      setRecentlyViewedSortSnapshot({ ...state.lastViewedAtByCanvasId });
    });
  }, []);
  const spaceOptions = useMemo(
    () => buildCanvasSpaceOptions(channels),
    [channels],
  );
  const canvasListUser = useMemo(
    () =>
      currentUser
        ? { uuid: currentUser.uuid, name: userDisplayName(currentUser) }
        : undefined,
    [currentUser],
  );
  const viewModel = useMemo(
    () =>
      canvasListService.buildViewModel({
        canvases: dashboards,
        spaces: channels,
        currentUser: canvasListUser,
        settings,
        query,
        lastViewedAtByCanvasId: recentlyViewedSortSnapshot,
      }),
    [
      canvasListService,
      canvasListUser,
      channels,
      dashboards,
      query,
      recentlyViewedSortSnapshot,
      settings,
    ],
  );
  const changeSettings = (nextSettings: CanvasListSettings): void => {
    const update = canvasListService.updateSettings({
      canvases: dashboards,
      spaces: channels,
      currentUser: canvasListUser,
      currentSettings: viewModel.settings,
      nextSettings,
    });
    if (update.refreshRecentlyViewedSnapshot) {
      setRecentlyViewedSortSnapshot({
        ...useCanvasViewedStore.getState().lastViewedAtByCanvasId,
      });
    }
    setSettings(update.settings);
  };
  const open = (canvas: DashboardRecord): void => {
    track(ANALYTICS_EVENTS.DASHBOARD_ACTION, {
      action_type: "open",
      surface: "canvases_pane",
      channel_id: canvas.channelId,
      dashboard_id: canvas.id,
      template_id: canvas.templateId,
    });
    void navigate({ to: "/canvases", search: { canvas: canvas.id } });
  };
  return (
    <CanvasList
      viewModel={viewModel}
      lastViewedAtByCanvasId={lastViewedAtByCanvasId}
      selectedId={selectedId}
      query={query}
      setQuery={setQuery}
      open={open}
      isLoading={isLoading}
      className={className}
      actions={
        <CanvasFilterMenu
          spaceOptions={spaceOptions}
          creatorOptions={viewModel.creatorOptions}
          createdByDisabled={viewModel.personalSpaceSelected}
          settings={viewModel.settings}
          onChange={changeSettings}
        />
      }
    />
  );
}
