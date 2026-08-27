import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { formatShortDayLabel, getLocalDayKey } from "@posthog/shared";

export type CanvasListSort = "recently_viewed" | "created_by";
export type CanvasListGrouping = "none" | "space" | "date";

export const DEFAULT_CANVAS_LIST_SORT: CanvasListSort = "recently_viewed";
export const DEFAULT_CANVAS_LIST_GROUPING: CanvasListGrouping = "date";

export interface CanvasListSection {
  key: string;
  label: string | null;
  canvases: DashboardRecord[];
}

export function filterCanvasList(
  canvases: readonly DashboardRecord[],
  {
    spaceIds,
    creatorUuids,
    query,
  }: {
    spaceIds: readonly string[];
    creatorUuids: readonly string[];
    query: string;
  },
): DashboardRecord[] {
  const normalizedQuery = query.toLowerCase();
  return canvases.filter(
    (canvas) =>
      (spaceIds.length === 0 || spaceIds.includes(canvas.channelId)) &&
      (creatorUuids.length === 0 ||
        (canvas.createdByUuid !== null &&
          canvas.createdByUuid !== undefined &&
          creatorUuids.includes(canvas.createdByUuid))) &&
      (normalizedQuery === "" ||
        `${canvas.name} ${canvas.description}`
          .toLowerCase()
          .includes(normalizedQuery)),
  );
}

function compareByCreator(
  first: DashboardRecord,
  second: DashboardRecord,
): number {
  const creator = (first.createdBy ?? "Unknown").localeCompare(
    second.createdBy ?? "Unknown",
  );
  if (creator !== 0) return creator;
  return first.name.localeCompare(second.name);
}

export function sortCanvasList(
  canvases: readonly DashboardRecord[],
  sort: CanvasListSort,
  lastViewedAtByCanvasId: Readonly<Record<string, number>>,
): DashboardRecord[] {
  return [...canvases].sort((first, second) => {
    if (sort === "created_by") return compareByCreator(first, second);

    const lastViewed =
      (lastViewedAtByCanvasId[second.id] ?? 0) -
      (lastViewedAtByCanvasId[first.id] ?? 0);
    if (lastViewed !== 0) return lastViewed;
    return second.updatedAt - first.updatedAt;
  });
}

export function groupCanvasList(
  canvases: readonly DashboardRecord[],
  grouping: CanvasListGrouping,
  spaceNames: ReadonlyMap<string, string>,
  now: Date = new Date(),
): CanvasListSection[] {
  if (canvases.length === 0) return [];
  if (grouping === "none") {
    return [{ key: "all", label: null, canvases: [...canvases] }];
  }

  if (grouping === "space") {
    const sections = new Map<string, CanvasListSection>();
    for (const canvas of canvases) {
      const key = `space:${canvas.channelId}`;
      const section = sections.get(key);
      if (section) {
        section.canvases.push(canvas);
      } else {
        sections.set(key, {
          key,
          label: spaceNames.get(canvas.channelId) ?? "Unknown space",
          canvases: [canvas],
        });
      }
    }
    return [...sections.values()];
  }

  const sections = new Map<
    string,
    { timestamp: number; canvases: DashboardRecord[] }
  >();
  for (const canvas of canvases) {
    const key = getLocalDayKey(canvas.createdAt);
    const section = sections.get(key);
    if (section) {
      section.canvases.push(canvas);
    } else {
      sections.set(key, {
        timestamp: canvas.createdAt,
        canvases: [canvas],
      });
    }
  }

  return [...sections.entries()]
    .sort(([, first], [, second]) => second.timestamp - first.timestamp)
    .map(([key, section]) => ({
      key: `date:${key}`,
      label: formatShortDayLabel(section.timestamp, now),
      canvases: section.canvases,
    }));
}
