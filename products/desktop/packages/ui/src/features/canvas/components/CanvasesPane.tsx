import { BlueprintIcon } from "@phosphor-icons/react";
import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import {
  Autocomplete,
  AutocompleteItem,
  AutocompleteList,
  cn,
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  MenuLabel,
  Spinner,
} from "@posthog/quill";
import { formatAbsoluteDateTime, formatRelativeAge } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { CanvasFilterMenu } from "@posthog/ui/features/canvas/components/CanvasFilterMenu";
import { buildCanvasCreatorOptions } from "@posthog/ui/features/canvas/components/canvasCreatorOptions";
import {
  type CanvasListGrouping,
  type CanvasListSort,
  DEFAULT_CANVAS_LIST_GROUPING,
  DEFAULT_CANVAS_LIST_SORT,
  filterCanvasList,
  groupCanvasList,
  sortCanvasList,
} from "@posthog/ui/features/canvas/components/canvasList";
import { buildCanvasSpaceOptions } from "@posthog/ui/features/canvas/components/canvasSpaceOptions";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { SidebarSearchHeader } from "@posthog/ui/features/canvas/components/SidebarSearchHeader";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { useAllCanvases } from "@posthog/ui/features/canvas/hooks/useDashboards";
import { useCanvasViewedStore } from "@posthog/ui/features/canvas/stores/canvasViewedStore";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { track } from "@posthog/ui/shell/analytics";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import {
  Fragment,
  type ReactElement,
  useEffect,
  useMemo,
  useState,
} from "react";

export function CanvasesPane({
  className,
}: {
  className?: string;
}): ReactElement {
  const { dashboards, isLoading } = useAllCanvases();
  const { channels } = useChannels();
  const { data: currentUser } = useMeQuery();
  const navigate = useNavigate();
  const selectedId = useRouterState({
    select: (state) =>
      (
        state.matches.find((match) => match.fullPath === "/canvases")?.search as
          | { canvas?: string }
          | undefined
      )?.canvas,
  });
  const [query, setQuery] = useState("");
  const [spaceIds, setSpaceIds] = useState<string[]>([]);
  const [creatorUuids, setCreatorUuids] = useState<string[]>([]);
  const [sort, setSort] = useState<CanvasListSort>(DEFAULT_CANVAS_LIST_SORT);
  const [grouping, setGrouping] = useState<CanvasListGrouping>(
    DEFAULT_CANVAS_LIST_GROUPING,
  );
  const [recentlyViewedSortSnapshot, setRecentlyViewedSortSnapshot] = useState<
    Record<string, number>
  >(() => ({ ...useCanvasViewedStore.getState().lastViewedAtByCanvasId }));
  const lastViewedAtByCanvasId = useCanvasViewedStore(
    (state) => state.lastViewedAtByCanvasId,
  );
  const markCanvasViewed = useCanvasViewedStore(
    (state) => state.markCanvasViewed,
  );
  useEffect(() => {
    if (selectedId) markCanvasViewed(selectedId, Date.now());
  }, [markCanvasViewed, selectedId]);
  useEffect(
    () =>
      useCanvasViewedStore.persist.onFinishHydration((state) => {
        setRecentlyViewedSortSnapshot({ ...state.lastViewedAtByCanvasId });
      }),
    [],
  );
  const channelNames = useMemo(
    () =>
      new Map(
        channels.map((channel) => [
          channel.id,
          channel.channelType === "personal" ? "personal" : channel.name,
        ]),
      ),
    [channels],
  );
  const spaceOptions = useMemo(
    () => buildCanvasSpaceOptions(channels),
    [channels],
  );
  const creatorOptions = useMemo(
    () =>
      buildCanvasCreatorOptions(
        dashboards,
        currentUser
          ? { uuid: currentUser.uuid, name: userDisplayName(currentUser) }
          : undefined,
      ),
    [currentUser, dashboards],
  );
  const shown = useMemo(
    () =>
      sortCanvasList(
        filterCanvasList(dashboards, { spaceIds, creatorUuids, query }),
        sort,
        recentlyViewedSortSnapshot,
      ),
    [
      creatorUuids,
      dashboards,
      query,
      recentlyViewedSortSnapshot,
      sort,
      spaceIds,
    ],
  );
  const sections = useMemo(
    () => groupCanvasList(shown, grouping, channelNames),
    [channelNames, grouping, shown],
  );
  const optionValues = shown.map((canvas) => canvas.id);
  const filtersActive =
    spaceIds.length > 0 ||
    creatorUuids.length > 0 ||
    sort !== DEFAULT_CANVAS_LIST_SORT ||
    grouping !== DEFAULT_CANVAS_LIST_GROUPING;
  const changeSort = (nextSort: CanvasListSort): void => {
    if (nextSort === DEFAULT_CANVAS_LIST_SORT) {
      setRecentlyViewedSortSnapshot({
        ...useCanvasViewedStore.getState().lastViewedAtByCanvasId,
      });
    }
    setSort(nextSort);
  };
  const clearFilters = (): void => {
    setSpaceIds([]);
    setCreatorUuids([]);
    changeSort(DEFAULT_CANVAS_LIST_SORT);
    setGrouping(DEFAULT_CANVAS_LIST_GROUPING);
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
    <Autocomplete<string>
      inline
      open
      value={query}
      items={optionValues}
      filter={null}
      onValueChange={(value, eventDetails) => {
        if (
          eventDetails.reason === "input-change" &&
          typeof value === "string"
        ) {
          setQuery(value);
        }
      }}
    >
      <div className={cn("flex min-h-0 flex-col", className)}>
        <SidebarSearchHeader
          title="Canvases"
          query={query}
          placeholder="Search canvases…"
          searchLabel="Search canvases"
          onClear={() => setQuery("")}
          actions={
            <CanvasFilterMenu
              spaceOptions={spaceOptions}
              spaceIds={spaceIds}
              onSpaceChange={setSpaceIds}
              creatorOptions={creatorOptions}
              creatorUuids={creatorUuids}
              onCreatorChange={setCreatorUuids}
              sort={sort}
              onSortChange={changeSort}
              grouping={grouping}
              onGroupingChange={setGrouping}
              onClear={clearFilters}
              active={filtersActive}
            />
          }
        />
        <AutocompleteList className="sidebar-autocomplete-tree scroll-mask-8 !max-h-none !p-1.5 min-h-0 flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          ) : shown.length === 0 ? (
            <Empty className="border-0 py-8">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <BlueprintIcon />
                </EmptyMedia>
                <EmptyTitle>No canvases match</EmptyTitle>
                <EmptyDescription>
                  Try another search or filter.
                </EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : (
            <div className="flex flex-col gap-px">
              {sections.map((section) => (
                <Fragment key={section.key}>
                  {section.label ? (
                    <MenuLabel>{section.label}</MenuLabel>
                  ) : null}
                  {section.canvases.map((canvas) => {
                    const lastViewedAt = lastViewedAtByCanvasId[canvas.id];
                    const lastViewedLabel = lastViewedAt
                      ? `Last viewed ${formatRelativeAge(lastViewedAt)}`
                      : "Not viewed yet";
                    const lastViewedTitle = lastViewedAt
                      ? `Last viewed ${formatAbsoluteDateTime(lastViewedAt)}`
                      : lastViewedLabel;

                    return (
                      <AutocompleteItem
                        key={canvas.id}
                        value={canvas.id}
                        nativeButton
                        className={cn(
                          "h-auto w-full items-start py-1.5 text-left ring-offset-0 data-highlighted:border-transparent data-highlighted:bg-fill-hover data-highlighted:ring-0 [&>span]:w-full [&>span]:items-start [&>span]:gap-2",
                          canvas.id === selectedId && "bg-fill-selected",
                        )}
                        onClick={() => open(canvas)}
                      >
                        {iconForTemplate(canvas.templateId, { size: 14 })}
                        <span className="min-w-0">
                          <span className="block truncate text-[13px]">
                            {canvas.name}
                          </span>
                          <span
                            className="block truncate text-muted-foreground text-xxs"
                            title={lastViewedTitle}
                          >
                            {canvas.createdBy ?? "Unknown"} · {lastViewedLabel}
                          </span>
                        </span>
                      </AutocompleteItem>
                    );
                  })}
                </Fragment>
              ))}
            </div>
          )}
        </AutocompleteList>
      </div>
    </Autocomplete>
  );
}
