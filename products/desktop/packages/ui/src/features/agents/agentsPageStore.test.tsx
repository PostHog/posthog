import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const location = vi.hoisted(() => ({
  state: { tabId: "first" },
  href: "/settings/agents",
}));
vi.mock("@tanstack/react-router", () => ({
  useRouterState: ({
    select,
  }: {
    select: (state: { location: typeof location }) => unknown;
  }) => select({ location }),
}));
vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: () => ({ history: { location } }),
}));

import {
  agentsPageActions,
  useAgentsPageActions,
  useAgentsTab,
  useOpenAgent,
} from "./agentsPageStore";

describe("agent browser tab selection", () => {
  it("restores a separate selection when tabs have the same href", () => {
    const { result, rerender } = renderHook(() => ({
      tab: useAgentsTab(),
      agent: useOpenAgent(),
      actions: useAgentsPageActions(),
    }));
    act(() =>
      result.current.actions.openAgent("first-agent", {
        findingId: "finding-1",
      }),
    );
    location.state.tabId = "second";
    rerender();
    expect(result.current.agent).toBeNull();
    act(() => result.current.actions.showTab("memory"));
    location.state.tabId = "first";
    rerender();
    expect(result.current.agent).toMatchObject({
      slug: "first-agent",
      tab: "output",
      findingId: "finding-1",
    });
    act(() => agentsPageActions().showTab("agents"));
    expect(result.current.agent).toBeNull();
    location.state.tabId = "second";
    rerender();
    expect(result.current.tab).toBe("memory");
  });
});
