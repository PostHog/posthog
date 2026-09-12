import { getRelativeDateGroup } from "@posthog/shared";

export type SpaceFileListSort = "recently_updated" | "name";
export type SpaceFileListGrouping = "none" | "space" | "date";

export interface SpaceFileListSettings {
  spaceIds: readonly string[];
  sort: SpaceFileListSort;
  grouping: SpaceFileListGrouping;
}

export const DEFAULT_SPACE_FILE_LIST_SORT: SpaceFileListSort =
  "recently_updated";
export const DEFAULT_SPACE_FILE_LIST_GROUPING: SpaceFileListGrouping = "space";
export const DEFAULT_SPACE_FILE_LIST_SETTINGS: SpaceFileListSettings = {
  spaceIds: [],
  sort: DEFAULT_SPACE_FILE_LIST_SORT,
  grouping: DEFAULT_SPACE_FILE_LIST_GROUPING,
};

/** The fields of a file this list reads. Narrower than the API summary. */
export interface SpaceFileListItem {
  id: string;
  channel_id: string;
  name: string;
  updated_at: string;
}

export interface SpaceFileListSection<Item extends SpaceFileListItem> {
  key: string;
  /** Null where the grouping draws no heading. */
  label: string | null;
  files: Item[];
}

export function hasCustomizedSpaceFileList(
  settings: SpaceFileListSettings,
): boolean {
  return (
    settings.spaceIds.length > 0 ||
    settings.sort !== DEFAULT_SPACE_FILE_LIST_SORT ||
    settings.grouping !== DEFAULT_SPACE_FILE_LIST_GROUPING
  );
}

function updatedAtMs(file: SpaceFileListItem): number {
  return new Date(file.updated_at).getTime();
}

function matchesQuery(
  file: SpaceFileListItem,
  spaceName: string,
  normalizedQuery: string,
): boolean {
  if (!normalizedQuery) return true;
  return (
    file.name.toLocaleLowerCase().includes(normalizedQuery) ||
    spaceName.toLocaleLowerCase().includes(normalizedQuery)
  );
}

function sortFiles<Item extends SpaceFileListItem>(
  files: Item[],
  sort: SpaceFileListSort,
): Item[] {
  if (sort === "name") {
    return files.sort((a, b) => a.name.localeCompare(b.name));
  }
  return files.sort((a, b) => updatedAtMs(b) - updatedAtMs(a));
}

/**
 * A date group covers today too, which `getRelativeDateGroup` leaves null so a
 * feed can lead with its newest rows unlabelled. A list of headings needs one.
 */
function dateGroupLabel(file: SpaceFileListItem): string {
  return getRelativeDateGroup(file.updated_at) ?? "Today";
}

export function buildSpaceFileSections<Item extends SpaceFileListItem>({
  files,
  spaceNames,
  query,
  settings,
}: {
  files: readonly Item[];
  spaceNames: ReadonlyMap<string, string>;
  query: string;
  settings: SpaceFileListSettings;
}): SpaceFileListSection<Item>[] {
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const selectedSpaces = new Set(settings.spaceIds);
  const unknownSpaceName = "Unknown space";

  const visible = files.filter((file) => {
    if (selectedSpaces.size > 0 && !selectedSpaces.has(file.channel_id)) {
      return false;
    }
    const spaceName = spaceNames.get(file.channel_id) ?? unknownSpaceName;
    return matchesQuery(file, spaceName, normalizedQuery);
  });

  if (settings.grouping === "none") {
    if (visible.length === 0) return [];
    return [
      {
        key: "all",
        label: null,
        files: sortFiles([...visible], settings.sort),
      },
    ];
  }

  const grouped = new Map<string, { label: string; files: Item[] }>();
  for (const file of visible) {
    const key =
      settings.grouping === "space" ? file.channel_id : dateGroupLabel(file);
    const label =
      settings.grouping === "space"
        ? (spaceNames.get(file.channel_id) ?? unknownSpaceName)
        : key;
    const section = grouped.get(key) ?? { label, files: [] };
    section.files.push(file);
    grouped.set(key, section);
  }

  const sections = [...grouped.entries()].map(([key, section]) => ({
    key,
    label: section.label,
    files: sortFiles(section.files, settings.sort),
  }));

  if (settings.grouping === "space") {
    return sections.sort((a, b) =>
      (a.label ?? "").localeCompare(b.label ?? ""),
    );
  }

  // Date sections read newest first, whatever order the files arrived in.
  return sections.sort(
    (a, b) => updatedAtMs(b.files[0]) - updatedAtMs(a.files[0]),
  );
}
