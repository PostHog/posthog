import { formatShortDayLabel, getLocalDayKey } from "@posthog/shared";
import { injectable } from "inversify";
import type { DashboardRecord } from "./dashboardSchemas";

export type CanvasListSort = "recently_viewed" | "created_by";
export type CanvasListGrouping = "none" | "space" | "date";

export interface CanvasListSettings {
  spaceIds: readonly string[];
  creatorUuids: readonly string[];
  sort: CanvasListSort;
  grouping: CanvasListGrouping;
}

export const DEFAULT_CANVAS_LIST_SORT: CanvasListSort = "recently_viewed";
export const DEFAULT_CANVAS_LIST_GROUPING: CanvasListGrouping = "date";
export const DEFAULT_CANVAS_LIST_SETTINGS: CanvasListSettings = {
  spaceIds: [],
  creatorUuids: [],
  sort: DEFAULT_CANVAS_LIST_SORT,
  grouping: DEFAULT_CANVAS_LIST_GROUPING,
};

export interface CanvasListSpace {
  id: string;
  name: string;
  channelType: "public" | "personal";
}

export interface CanvasListUser {
  uuid: string;
  name: string;
}

export interface CanvasCreatorOption {
  value: string | null;
  label: string;
  searchLabel?: string;
}

export interface CanvasListSection {
  key: string;
  label: string | null;
  canvases: DashboardRecord[];
}

export interface CanvasListViewModel {
  settings: CanvasListSettings;
  personalSpaceSelected: boolean;
  creatorOptions: CanvasCreatorOption[];
  canvases: DashboardRecord[];
  sections: CanvasListSection[];
}

interface CanvasListContext {
  canvases: readonly DashboardRecord[];
  spaces: readonly CanvasListSpace[];
  currentUser?: CanvasListUser;
}

interface BuildCanvasListViewModelInput extends CanvasListContext {
  settings: CanvasListSettings;
  query: string;
  lastViewedAtByCanvasId: Readonly<Record<string, number>>;
  now?: Date;
}

interface UpdateCanvasListSettingsInput extends CanvasListContext {
  currentSettings: CanvasListSettings;
  nextSettings: CanvasListSettings;
}

export interface CanvasListSettingsUpdate {
  settings: CanvasListSettings;
  refreshRecentlyViewedSnapshot: boolean;
}

export function hasCustomizedCanvasList(settings: CanvasListSettings): boolean {
  return (
    settings.spaceIds.length > 0 ||
    settings.creatorUuids.length > 0 ||
    settings.sort !== DEFAULT_CANVAS_LIST_SORT ||
    settings.grouping !== DEFAULT_CANVAS_LIST_GROUPING
  );
}

function personalSpaceId(
  spaces: readonly CanvasListSpace[],
): string | undefined {
  return spaces.find((space) => space.channelType === "personal")?.id;
}

function constrainSettingsToPersonalSpace(
  settings: CanvasListSettings,
  spaceId: string | undefined,
  currentUserUuid: string | undefined,
): CanvasListSettings {
  if (!spaceId || !settings.spaceIds.includes(spaceId)) return settings;

  const creatorUuids = currentUserUuid ? [currentUserUuid] : [];
  if (
    settings.creatorUuids.length === creatorUuids.length &&
    settings.creatorUuids.every((uuid, index) => uuid === creatorUuids[index])
  ) {
    return settings;
  }
  return { ...settings, creatorUuids };
}

function buildCanvasCreatorOptions(
  canvases: readonly DashboardRecord[],
  currentUser?: CanvasListUser,
  spaceIds: readonly string[] = [],
): CanvasCreatorOption[] {
  const selectedSpaceIds = new Set(spaceIds);
  const limitsCreatorsBySpace = selectedSpaceIds.size > 0;
  const creatorsByUuid = new Map<string, string>();
  let currentUserHasCanvas = false;
  for (const canvas of canvases) {
    if (limitsCreatorsBySpace && !selectedSpaceIds.has(canvas.channelId)) {
      continue;
    }
    if (canvas.createdByUuid === currentUser?.uuid) {
      currentUserHasCanvas = true;
      continue;
    }
    if (canvas.createdByUuid && !creatorsByUuid.has(canvas.createdByUuid)) {
      creatorsByUuid.set(canvas.createdByUuid, canvas.createdBy ?? "Unknown");
    }
  }

  const otherCreators = [...creatorsByUuid.entries()]
    .map(([value, label]) => ({ value, label }))
    .sort((a, b) => a.label.localeCompare(b.label));

  return [
    ...(currentUser && (!limitsCreatorsBySpace || currentUserHasCanvas)
      ? [
          {
            value: currentUser.uuid,
            label: "Me",
            searchLabel: currentUser.name,
          },
        ]
      : []),
    { value: null, label: "Anyone" },
    ...otherCreators,
  ];
}

function normalizeSettings(
  settings: CanvasListSettings,
  context: CanvasListContext,
): CanvasListSettings {
  const spaceId = personalSpaceId(context.spaces);
  const constrainedSettings = constrainSettingsToPersonalSpace(
    settings,
    spaceId,
    context.currentUser?.uuid,
  );
  if (spaceId && constrainedSettings.spaceIds.includes(spaceId)) {
    return constrainedSettings;
  }

  const availableCreatorUuids = new Set(
    buildCanvasCreatorOptions(
      context.canvases,
      context.currentUser,
      constrainedSettings.spaceIds,
    ).flatMap((option) => (option.value === null ? [] : [option.value])),
  );
  const creatorUuids = constrainedSettings.creatorUuids.filter((uuid) =>
    availableCreatorUuids.has(uuid),
  );
  if (creatorUuids.length === constrainedSettings.creatorUuids.length) {
    return constrainedSettings;
  }
  return { ...constrainedSettings, creatorUuids };
}

function filterCanvasList(
  canvases: readonly DashboardRecord[],
  settings: CanvasListSettings,
  query: string,
): DashboardRecord[] {
  const normalizedQuery = query.toLowerCase();
  return canvases.filter(
    (canvas) =>
      (settings.spaceIds.length === 0 ||
        settings.spaceIds.includes(canvas.channelId)) &&
      (settings.creatorUuids.length === 0 ||
        (canvas.createdByUuid != null &&
          settings.creatorUuids.includes(canvas.createdByUuid))) &&
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
  return creator !== 0 ? creator : first.name.localeCompare(second.name);
}

function sortCanvasList(
  canvases: readonly DashboardRecord[],
  sort: CanvasListSort,
  lastViewedAtByCanvasId: Readonly<Record<string, number>>,
): DashboardRecord[] {
  return [...canvases].sort((first, second) => {
    if (sort === "created_by") return compareByCreator(first, second);

    const lastViewed =
      (lastViewedAtByCanvasId[second.id] ?? 0) -
      (lastViewedAtByCanvasId[first.id] ?? 0);
    return lastViewed !== 0 ? lastViewed : second.updatedAt - first.updatedAt;
  });
}

function groupCanvasList(
  canvases: readonly DashboardRecord[],
  grouping: CanvasListGrouping,
  spaceNames: ReadonlyMap<string, string>,
  now: Date,
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
      sections.set(key, { timestamp: canvas.createdAt, canvases: [canvas] });
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

@injectable()
export class CanvasListService {
  buildViewModel(input: BuildCanvasListViewModelInput): CanvasListViewModel {
    const settings = normalizeSettings(input.settings, input);
    const spaceId = personalSpaceId(input.spaces);
    const canvases = sortCanvasList(
      filterCanvasList(input.canvases, settings, input.query),
      settings.sort,
      input.lastViewedAtByCanvasId,
    );
    const spaceNames = new Map(
      input.spaces.map((space) => [
        space.id,
        space.channelType === "personal" ? "personal" : space.name,
      ]),
    );

    return {
      settings,
      personalSpaceSelected: Boolean(
        spaceId && settings.spaceIds.includes(spaceId),
      ),
      creatorOptions: buildCanvasCreatorOptions(
        input.canvases,
        input.currentUser,
        settings.spaceIds,
      ),
      canvases,
      sections: groupCanvasList(
        canvases,
        settings.grouping,
        spaceNames,
        input.now ?? new Date(),
      ),
    };
  }

  updateSettings(
    input: UpdateCanvasListSettingsInput,
  ): CanvasListSettingsUpdate {
    const settings = normalizeSettings(input.nextSettings, input);
    return {
      settings,
      refreshRecentlyViewedSnapshot:
        input.currentSettings.sort !== DEFAULT_CANVAS_LIST_SORT &&
        settings.sort === DEFAULT_CANVAS_LIST_SORT,
    };
  }
}
