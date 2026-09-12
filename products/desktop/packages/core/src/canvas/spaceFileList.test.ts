import { describe, expect, it } from "vitest";
import {
  buildSpaceFileSections,
  DEFAULT_SPACE_FILE_LIST_SETTINGS,
  hasCustomizedSpaceFileList,
  type SpaceFileListItem,
  type SpaceFileListSettings,
} from "./spaceFileList";

const SPACE_NAMES = new Map([
  ["space-a", "alpha"],
  ["space-b", "beta"],
]);

function file(
  id: string,
  overrides: Partial<SpaceFileListItem> = {},
): SpaceFileListItem {
  return {
    id,
    channel_id: "space-a",
    name: `${id}.md`,
    updated_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

function settings(
  overrides: Partial<SpaceFileListSettings> = {},
): SpaceFileListSettings {
  return { ...DEFAULT_SPACE_FILE_LIST_SETTINGS, ...overrides };
}

function build(
  files: SpaceFileListItem[],
  overrides: Partial<SpaceFileListSettings> = {},
  query = "",
) {
  return buildSpaceFileSections({
    files,
    spaceNames: SPACE_NAMES,
    query,
    settings: settings(overrides),
  });
}

describe("spaceFileList", () => {
  it("keeps only the selected spaces", () => {
    const sections = build([file("a"), file("b", { channel_id: "space-b" })], {
      spaceIds: ["space-b"],
    });

    expect(
      sections.flatMap((section) => section.files.map((f) => f.id)),
    ).toEqual(["b"]);
  });

  it("matches a query against the space name as well as the file name", () => {
    const sections = build(
      [file("a"), file("b", { channel_id: "space-b" })],
      {},
      "beta",
    );

    expect(
      sections.flatMap((section) => section.files.map((f) => f.id)),
    ).toEqual(["b"]);
  });

  it.each([
    ["name" as const, ["early.md", "late.md"]],
    ["recently_updated" as const, ["late.md", "early.md"]],
  ])("sorts by %s", (sort, expected) => {
    const sections = build(
      [
        file("late", {
          name: "late.md",
          updated_at: "2026-09-11T00:00:00Z",
        }),
        file("early", {
          name: "early.md",
          updated_at: "2026-09-01T00:00:00Z",
        }),
      ],
      { sort, grouping: "none" },
    );

    expect(sections[0].files.map((f) => f.name)).toEqual(expected);
  });

  it.each([
    ["none" as const, 1, [null]],
    ["space" as const, 2, ["alpha", "beta"]],
  ])("groups by %s", (grouping, sectionCount, labels) => {
    const sections = build([file("a"), file("b", { channel_id: "space-b" })], {
      grouping,
    });

    expect(sections).toHaveLength(sectionCount);
    expect(sections.map((section) => section.label)).toEqual(labels);
  });

  it("drops no file when a space has no name", () => {
    const sections = build([file("orphan", { channel_id: "gone" })]);

    expect(sections.map((section) => section.label)).toEqual(["Unknown space"]);
    expect(sections[0].files.map((f) => f.id)).toEqual(["orphan"]);
  });

  it.each([
    [{}, false],
    [{ spaceIds: ["space-a"] }, true],
    [{ sort: "name" as const }, true],
    [{ grouping: "date" as const }, true],
  ])("reports customization for %o as %s", (overrides, expected) => {
    expect(hasCustomizedSpaceFileList(settings(overrides))).toBe(expected);
  });
});
