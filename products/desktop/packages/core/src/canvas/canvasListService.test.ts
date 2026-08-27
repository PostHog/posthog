import { describe, expect, it } from "vitest";
import {
  CanvasListService,
  type CanvasListSettings,
  DEFAULT_CANVAS_LIST_SETTINGS,
} from "./canvasListService";
import type { DashboardRecord } from "./dashboardSchemas";

const CURRENT_USER = { uuid: "me", name: "Current User" };
const SPACES = [
  { id: "personal", name: "me", channelType: "personal" as const },
  { id: "space-a", name: "alpha", channelType: "public" as const },
  { id: "space-b", name: "beta", channelType: "public" as const },
];

function canvas(
  id: string,
  overrides: Partial<DashboardRecord> = {},
): DashboardRecord {
  return {
    id,
    channelId: "space-a",
    name: id,
    kind: "freeform",
    description: "",
    componentMeta: null,
    templateId: "freeform",
    context: "",
    generationTaskId: null,
    createdAt: 1,
    updatedAt: 1,
    currentVersionId: null,
    publishedBuildId: null,
    ...overrides,
  };
}

function settings(
  overrides: Partial<CanvasListSettings> = {},
): CanvasListSettings {
  return { ...DEFAULT_CANVAS_LIST_SETTINGS, ...overrides };
}

function buildViewModel(
  canvases: DashboardRecord[],
  listSettings: CanvasListSettings = DEFAULT_CANVAS_LIST_SETTINGS,
) {
  return new CanvasListService().buildViewModel({
    canvases,
    spaces: SPACES,
    currentUser: CURRENT_USER,
    settings: listSettings,
    query: "",
    lastViewedAtByCanvasId: {},
    now: new Date(2026, 7, 20, 12),
  });
}

describe("CanvasListService", () => {
  it("combines space, creator, and search filters", () => {
    const service = new CanvasListService();
    const viewModel = service.buildViewModel({
      canvases: [
        canvas("match", {
          channelId: "space-a",
          createdByUuid: "ada",
          description: "revenue report",
        }),
        canvas("wrong-space", {
          channelId: "space-b",
          createdByUuid: "ada",
          description: "revenue report",
        }),
        canvas("wrong-creator", {
          channelId: "space-a",
          createdByUuid: "grace",
          description: "revenue report",
        }),
      ],
      spaces: SPACES,
      currentUser: CURRENT_USER,
      settings: settings({
        spaceIds: ["space-a"],
        creatorUuids: ["ada"],
      }),
      query: "revenue",
      lastViewedAtByCanvasId: {},
    });

    expect(viewModel.canvases.map(({ id }) => id)).toEqual(["match"]);
  });

  it.each([
    {
      sort: "recently_viewed" as const,
      views: { first: 20, second: 10 },
      canvases: [canvas("second"), canvas("first")],
      expected: ["first", "second"],
    },
    {
      sort: "created_by" as const,
      views: {} as Record<string, number>,
      canvases: [
        canvas("zulu", { createdBy: "Zoe" }),
        canvas("alpha", { createdBy: "Ada" }),
      ],
      expected: ["alpha", "zulu"],
    },
  ])("sorts canvases by $sort", ({ sort, views, canvases, expected }) => {
    const viewModel = new CanvasListService().buildViewModel({
      canvases,
      spaces: SPACES,
      currentUser: CURRENT_USER,
      settings: settings({ sort }),
      query: "",
      lastViewedAtByCanvasId: views,
    });

    expect(viewModel.canvases.map(({ id }) => id)).toEqual(expected);
  });

  it.each([
    { grouping: "none" as const, expected: [[null, "pinned", "a", "b"]] },
    {
      grouping: "space" as const,
      expected: [
        ["alpha", "pinned", "a"],
        ["beta", "b"],
      ],
    },
    {
      grouping: "date" as const,
      expected: [
        ["Today", "b"],
        ["Yesterday", "pinned", "a"],
      ],
    },
  ])(
    "groups canvases by $grouping, pinned ones leading their group",
    ({ grouping, expected }) => {
      const canvases = [
        canvas("a", {
          channelId: "space-a",
          createdAt: new Date(2026, 7, 19, 8).getTime(),
          updatedAt: 3,
        }),
        canvas("b", {
          channelId: "space-b",
          createdAt: new Date(2026, 7, 20, 8).getTime(),
          updatedAt: 2,
        }),
        // Last by the sort and grouped with "a", so only the pin can lift it.
        canvas("pinned", {
          channelId: "space-a",
          createdAt: new Date(2026, 7, 19, 7).getTime(),
          updatedAt: 1,
          pinnedAt: 5,
        }),
      ];

      const viewModel = buildViewModel(canvases, settings({ grouping }));
      expect(
        viewModel.sections.map((section) => [
          section.label,
          ...section.canvases.map(({ id }) => id),
        ]),
      ).toEqual(expected);
    },
  );

  it("keeps the chosen sort order among pinned canvases", () => {
    const viewModel = buildViewModel(
      [
        canvas("zulu", { createdBy: "Zoe", pinnedAt: 9 }),
        canvas("ada", { createdBy: "Ada", pinnedAt: 1 }),
        canvas("unpinned", { createdBy: "Bea" }),
      ],
      settings({ sort: "created_by", grouping: "none" }),
    );

    expect(viewModel.canvases.map(({ id }) => id)).toEqual([
      "ada",
      "zulu",
      "unpinned",
    ]);
  });

  it("limits creator options to creators in the selected spaces", () => {
    const viewModel = buildViewModel(
      [
        canvas("mine", {
          channelId: "space-a",
          createdByUuid: "me",
          createdBy: "Current User",
        }),
        canvas("ada", {
          channelId: "space-a",
          createdByUuid: "ada",
          createdBy: "Ada Lovelace",
        }),
        canvas("grace", {
          channelId: "space-b",
          createdByUuid: "grace",
          createdBy: "Grace Hopper",
        }),
      ],
      settings({ spaceIds: ["space-a"] }),
    );

    expect(viewModel.creatorOptions).toEqual([
      { value: "me", label: "Me", searchLabel: "Current User" },
      { value: null, label: "Anyone" },
      { value: "ada", label: "Ada Lovelace" },
    ]);
  });

  it("forces the current user when the personal space is selected", () => {
    const viewModel = buildViewModel(
      [
        canvas("mine", {
          channelId: "personal",
          createdByUuid: "me",
        }),
      ],
      settings({ spaceIds: ["personal"], creatorUuids: ["ada"] }),
    );

    expect(viewModel.personalSpaceSelected).toBe(true);
    expect(viewModel.settings.creatorUuids).toEqual(["me"]);
  });

  it("removes creators that are unavailable after a space change", () => {
    const update = new CanvasListService().updateSettings({
      canvases: [
        canvas("ada", {
          channelId: "space-a",
          createdByUuid: "ada",
        }),
      ],
      spaces: SPACES,
      currentUser: CURRENT_USER,
      currentSettings: settings({ creatorUuids: ["ada"] }),
      nextSettings: settings({
        spaceIds: ["space-b"],
        creatorUuids: ["ada"],
      }),
    });

    expect(update.settings.creatorUuids).toEqual([]);
  });
});
