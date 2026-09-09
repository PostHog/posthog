import { describe, expect, it, vi } from "vitest";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: () => ({ navigate }),
}));

import {
  type AgentsPageSearch,
  agentsPageActions,
  agentsTabFrom,
  openAgentFrom,
} from "./agentsPageStore";

const lastCall = () =>
  navigate.mock.lastCall?.[0] as {
    to: string;
    params: { category: string };
    replace: boolean;
    search: (previous: AgentsPageSearch) => AgentsPageSearch;
  };

const lastSearch = (previous: AgentsPageSearch): AgentsPageSearch =>
  lastCall().search(previous);

describe("agents page selection", () => {
  it.each([
    [{}, "agents"],
    [{ tab: "memory" }, "memory"],
    [{ tab: "nonsense" }, "agents"],
  ])("reads the page tab from %o", (search, tab) =>
    expect(agentsTabFrom(search)).toBe(tab),
  );

  it.each([
    [{}, null],
    [
      { agent: "signals-scout-aio" },
      { slug: "signals-scout-aio", tab: "activity" },
    ],
    [
      { agent: "a", finding: "f-1" },
      { slug: "a", tab: "output", findingId: "f-1" },
    ],
    [
      { agent: "a", agentTab: "settings" },
      { slug: "a", tab: "settings" },
    ],
    [
      { agent: "a", agentTab: "nonsense" },
      { slug: "a", tab: "activity" },
    ],
  ])("reads the open agent from %o", (search, agent) =>
    agent
      ? expect(openAgentFrom(search)).toMatchObject(agent)
      : expect(openAgentFrom(search)).toBeNull(),
  );

  it("puts the open agent in the URL and keeps the report source", () => {
    agentsPageActions().openAgent("signals-scout-aio", { tab: "output" });
    const { to, params, replace } = lastCall();
    expect(to).toBe("/settings/$category");
    expect(params).toEqual({ category: "agents" });
    expect(replace).toBe(false);
    expect(lastSearch({ from: "/inbox/reports" })).toEqual({
      from: "/inbox/reports",
      agent: "signals-scout-aio",
      agentTab: "output",
    });
  });

  it("drops the agent when returning to a page tab", () =>
    expect(
      (agentsPageActions().showTab("memory"),
      lastSearch({ from: "/activity", agent: "a", agentTab: "output" })),
    ).toEqual({ from: "/activity", tab: "memory" }));

  it("replaces the entry when switching the agent's own tab", () => {
    agentsPageActions().showAgentTab("settings");
    expect(lastCall().replace).toBe(true);
    expect(lastSearch({ agent: "a", finding: "f-1" })).toEqual({
      agent: "a",
      agentTab: "settings",
      finding: undefined,
    });
  });
});
