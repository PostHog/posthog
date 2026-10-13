import { describe, expect, it } from "vitest";
import {
  orderTaskRepositoryItems,
  resolveTaskRepositorySelection,
  taskRepositoryLabel,
} from "./TaskRepositoryChip";

const integrationIds: Record<string, number> = {
  "acme/web": 7,
  "acme/api": 7,
};
const getIntegrationIdForRepo = (repository: string) =>
  integrationIds[repository];

describe("TaskRepositoryChip", () => {
  it.each([
    [[], "Add repositories…"],
    [["acme/web"], "acme/web"],
    [["acme/web", "acme/api"], "2 repositories"],
  ])("labels %j as %s", (repositories, label) => {
    expect(taskRepositoryLabel(repositories)).toBe(label);
  });

  it.each([
    {
      name: "adds a repository with its integration",
      current: [],
      next: ["acme/web"],
      integrationId: null,
      max: 10,
      expected: { repositories: ["acme/web"], integrationId: 7 },
    },
    {
      name: "clears the integration when the last repository is removed",
      current: ["acme/web"],
      next: [],
      integrationId: 7,
      max: 10,
      expected: { repositories: [], integrationId: null },
    },
    {
      name: "ignores a repository with no known integration",
      current: ["acme/web"],
      next: ["acme/web", "other/repo"],
      integrationId: 7,
      max: 10,
      expected: null,
    },
    {
      name: "ignores an add past the limit",
      current: ["acme/web"],
      next: ["acme/web", "acme/api"],
      integrationId: 7,
      max: 1,
      expected: null,
    },
  ])("$name", ({ current, next, integrationId, max, expected }) => {
    expect(
      resolveTaskRepositorySelection({
        current,
        next,
        integrationId,
        getIntegrationIdForRepo,
        max,
      }),
    ).toEqual(expected);
  });

  it.each([
    {
      name: "keeps a repository picked while open in its place",
      pinned: ["acme/api"],
      selected: ["acme/api", "acme/web"],
      fetched: ["acme/api", "acme/docs", "acme/web"],
      query: "",
      expected: ["acme/api", "acme/docs", "acme/web"],
    },
    {
      name: "lists a selected repository the search page misses",
      pinned: [],
      selected: ["acme/web"],
      fetched: ["acme/docs"],
      query: "acme",
      expected: ["acme/docs", "acme/web"],
    },
    {
      name: "drops results left over from the previous query",
      pinned: [],
      selected: [],
      fetched: ["acme/docs", "acme/web"],
      query: "web",
      expected: ["acme/web"],
    },
  ])("$name", ({ pinned, selected, fetched, query, expected }) => {
    expect(
      orderTaskRepositoryItems({ pinned, selected, fetched, query }),
    ).toEqual(expected);
  });
});
