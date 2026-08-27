import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import { describe, expect, it } from "vitest";
import {
  filterCanvasList,
  groupCanvasList,
  sortCanvasList,
} from "./canvasList";

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

describe("canvasList", () => {
  it("matches any selected space and creator", () => {
    const canvases = [
      canvas("first", { channelId: "space-a", createdByUuid: "ada" }),
      canvas("second", { channelId: "space-b", createdByUuid: "ada" }),
      canvas("third", { channelId: "space-a", createdByUuid: "grace" }),
    ];

    expect(
      filterCanvasList(canvases, {
        spaceIds: ["space-a", "space-b"],
        creatorUuids: ["ada"],
        query: "",
      }).map(({ id }) => id),
    ).toEqual(["first", "second"]);
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
    expect(sortCanvasList(canvases, sort, views).map(({ id }) => id)).toEqual(
      expected,
    );
  });

  it.each([
    {
      grouping: "none" as const,
      expected: [[null, "a", "b"]],
    },
    {
      grouping: "space" as const,
      expected: [
        ["#alpha", "a"],
        ["#beta", "b"],
      ],
    },
    {
      grouping: "date" as const,
      expected: [
        ["Today", "b"],
        ["Yesterday", "a"],
      ],
    },
  ])("groups canvases by $grouping", ({ grouping, expected }) => {
    const now = new Date(2026, 7, 20, 12);
    const canvases = [
      canvas("a", {
        channelId: "space-a",
        createdAt: new Date(2026, 7, 19, 8).getTime(),
      }),
      canvas("b", {
        channelId: "space-b",
        createdAt: new Date(2026, 7, 20, 8).getTime(),
      }),
    ];
    const sections = groupCanvasList(
      canvases,
      grouping,
      new Map([
        ["space-a", "#alpha"],
        ["space-b", "#beta"],
      ]),
      now,
    );

    expect(
      sections.map((section) => [
        section.label,
        ...section.canvases.map(({ id }) => id),
      ]),
    ).toEqual(expected);
  });
});
