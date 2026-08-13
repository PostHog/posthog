import type { UserBasic } from "@posthog/shared/domain-types";
import { describe, expect, it } from "vitest";
import {
  filterHomeRows,
  groupHomeRows,
  type HomeFilters,
  homeFacets,
  NO_HOME_FILTERS,
  sortHomeRows,
  toggleHomeFilter,
} from "./homeFilters";
import type { HomeRow } from "./homeRows";

const ADA: UserBasic = {
  id: 1,
  uuid: "ada-uuid",
  email: "ada@example.com",
  first_name: "Ada",
  last_name: "Lovelace",
};

function row(overrides: Partial<HomeRow> = {}): HomeRow {
  return {
    key: overrides.id ? `session:${overrides.id}` : "session:row-1",
    kind: "session",
    id: "row-1",
    title: "Fix the export",
    status: "in_progress",
    reference: "#128",
    spaceId: "space-1",
    spaceName: "ux-platform",
    projectId: "project-1",
    projectName: "Onboarding",
    assignee: ADA,
    createdAt: 10,
    updatedAt: 20,
    pinned: false,
    environment: "cloud",
    source: null,
    task: null,
    ...overrides,
  };
}

function filters(overrides: Partial<HomeFilters> = {}): HomeFilters {
  return { ...NO_HOME_FILTERS, ...overrides };
}

describe("home filters", () => {
  it("keeps every row while no facet is set", () => {
    const rows = [row({ id: "a" }), row({ id: "b", status: "done" })];

    expect(
      filterHomeRows(rows, { query: "", filters: NO_HOME_FILTERS }),
    ).toHaveLength(2);
  });

  it.each<[string, Partial<HomeFilters>, string[]]>([
    ["status", { statuses: ["done"] }, ["done-row"]],
    ["kind", { kinds: ["canvas"] }, ["canvas-row"]],
    ["space", { spaceIds: ["space-2"] }, ["other-space-row"]],
    ["project", { projectIds: ["project-2"] }, ["other-project-row"]],
    ["assignee", { assigneeUuids: ["ada-uuid"] }, ["assigned-row"]],
  ])("narrows on %s", (_facet, narrowed, expected) => {
    const rows = [
      row({ id: "done-row", status: "done", assignee: null, projectId: null }),
      row({
        id: "canvas-row",
        kind: "canvas",
        assignee: null,
        projectId: null,
      }),
      row({
        id: "other-space-row",
        spaceId: "space-2",
        assignee: null,
        projectId: null,
      }),
      row({
        id: "other-project-row",
        projectId: "project-2",
        projectName: "Billing",
        assignee: null,
      }),
      row({
        id: "assigned-row",
        projectId: null,
        status: "todo",
        kind: "plan",
      }),
    ];

    expect(
      filterHomeRows(rows, { query: "", filters: filters(narrowed) })
        .map((match) => match.id)
        .sort(),
    ).toEqual(expected);
  });

  it("excludes unassigned work when filtering by assignee", () => {
    const rows = [
      row({ id: "assigned" }),
      row({ id: "nobody", assignee: null }),
    ];

    expect(
      filterHomeRows(rows, {
        query: "",
        filters: filters({ assigneeUuids: ["ada-uuid"] }),
      }).map((match) => match.id),
    ).toEqual(["assigned"]);
  });

  it.each([
    ["a title", "export"],
    ["a project name", "onboard"],
    ["a space name", "ux-plat"],
    ["a reference", "#128"],
  ])("searches %s", (_field, query) => {
    expect(
      filterHomeRows([row()], { query, filters: NO_HOME_FILTERS }),
    ).toHaveLength(1);
  });

  it("adds and removes one value without disturbing the other facets", () => {
    const withStatus = toggleHomeFilter(
      filters({ kinds: ["canvas"] }),
      "statuses",
      "done",
    );
    expect(withStatus).toMatchObject({ statuses: ["done"], kinds: ["canvas"] });

    expect(toggleHomeFilter(withStatus, "statuses", "done")).toMatchObject({
      statuses: [],
      kinds: ["canvas"],
    });
  });

  it("floats pinned work above the chosen order", () => {
    const rows = [
      row({ id: "newest", updatedAt: 100 }),
      row({ id: "pinned", updatedAt: 1, pinned: true }),
    ];

    expect(sortHomeRows(rows, "recent").map((match) => match.id)).toEqual([
      "pinned",
      "newest",
    ]);
  });
});

describe("home grouping", () => {
  it("keeps statuses in their canonical order and drops the empty ones", () => {
    const rows = [
      row({ id: "done", status: "done" }),
      row({ id: "failed", status: "failed" }),
      row({ id: "running", status: "in_progress" }),
    ];

    expect(groupHomeRows(rows, "status").map((group) => group.key)).toEqual([
      "failed",
      "in_progress",
      "done",
    ]);
  });

  it.each<["project" | "assignee", Partial<HomeRow>, string]>([
    ["project", { projectId: null, projectName: null }, "No project"],
    ["assignee", { assignee: null }, "Unassigned"],
  ])(
    "puts work with no %s in its own group, last",
    (groupBy, missing, label) => {
      const groups = groupHomeRows(
        [row({ id: "has-one" }), row({ id: "missing", ...missing })],
        groupBy,
      );

      expect(groups.at(-1)).toMatchObject({ label, rows: [{ id: "missing" }] });
    },
  );

  it("leads with the busiest group when grouping by space", () => {
    const rows = [
      row({ id: "a", spaceId: "quiet", spaceName: "quiet" }),
      row({ id: "b", spaceId: "busy", spaceName: "busy" }),
      row({ id: "c", spaceId: "busy", spaceName: "busy" }),
    ];

    expect(groupHomeRows(rows, "space").map((group) => group.label)).toEqual([
      "#busy",
      "#quiet",
    ]);
  });
});

describe("home facets", () => {
  it("offers only the values present, with their counts", () => {
    const rows = [
      row({ id: "a", status: "done" }),
      row({ id: "b", status: "done" }),
      row({ id: "c", status: "failed" }),
    ];

    expect(homeFacets(rows).statuses).toEqual([
      { value: "failed", label: "Failed", count: 1 },
      { value: "done", label: "Done", count: 2 },
    ]);
  });

  it("leaves unfiled work out of the project facet", () => {
    const rows = [
      row({ id: "a" }),
      row({ id: "b", projectId: null, projectName: null }),
    ];

    expect(homeFacets(rows).projects).toEqual([
      { value: "project-1", label: "Onboarding", count: 1 },
    ]);
  });
});
