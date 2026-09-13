import { recordApiRequest } from "@posthog/ui/shell/posthogAnalyticsImpl";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useLoopsClient } from "./useLoopsClient";

vi.mock("@posthog/ui/shell/posthogAnalyticsImpl", () => ({
  recordApiRequest: vi.fn(),
}));
vi.mock("@posthog/ui/router/routerRef", () => ({
  getRouterOrNull: () => ({
    state: { matches: [{ routeId: "/_shell/spaces/$channelId/loops" }] },
  }),
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    auth: {
      getValidAccessToken: { query: async () => ({ accessToken: "token" }) },
      refreshAccessToken: { mutate: async () => ({ accessToken: "fresh" }) },
    },
  }),
}));
vi.mock("../../auth/store", () => ({
  useAuthStateValue: (select: (state: unknown) => unknown) =>
    select({ status: "authenticated", cloudRegion: "us", currentProjectId: 7 }),
}));

const mockedRecordApiRequest = vi.mocked(recordApiRequest);

describe("useLoopsClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("records request timing against the route the request started on", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );
    const { result } = renderHook(() => useLoopsClient());
    const loops = result.current;
    if (!loops) throw new Error("expected an authenticated Loops client");
    const path = `/api/projects/${loops.projectId}/loops/`;

    await loops.client.fetcher.fetch({
      method: "get",
      path,
      url: new URL(`https://us.posthog.com${path}`),
    });

    expect(mockedRecordApiRequest).toHaveBeenCalledWith(
      expect.any(Number),
      "/_shell/spaces/$channelId/loops",
      "GET",
      path,
      200,
      "success",
    );
  });
});
