import { beforeEach, expect, it } from "vitest";
import { resetRailHistory, useRailHistoryStore } from "./railHistoryStore";

beforeEach(() => resetRailHistory());

it("forgets every remembered destination on reset", () => {
  // A project or account switch calls this; without it a later rail pick would
  // restore a page — or re-scope the app to a space — from the old project.
  useRailHistoryStore.getState().record("spaces", {
    href: "/spaces/old-space",
    spaces: { listOpen: true, spaceId: "old-space" },
  });
  useRailHistoryStore.getState().record("inbox", { href: "/inbox/pulls/1" });
  expect(useRailHistoryStore.getState().lastByPane).not.toEqual({});

  resetRailHistory();

  expect(useRailHistoryStore.getState().lastByPane).toEqual({});
});
