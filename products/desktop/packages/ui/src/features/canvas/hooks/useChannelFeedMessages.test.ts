import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useChannelFeedMessages } from "./useChannelFeedMessages";

vi.mock("@posthog/ui/hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: vi.fn(() => ({ data: [], isLoading: false })),
}));

describe("useChannelFeedMessages", () => {
  beforeEach(() => {
    vi.mocked(useAuthenticatedQuery).mockClear();
  });

  function refetchInterval() {
    renderHook(() => useChannelFeedMessages("channel-id"));

    return vi.mocked(useAuthenticatedQuery).mock.calls[0]?.[2]?.refetchInterval;
  }

  it("keeps polling after a transient query error", () => {
    const interval = refetchInterval();

    expect(interval).toBeTypeOf("function");
    expect(
      typeof interval === "function"
        ? interval({ state: { error: new Error("Network failure") } } as never)
        : interval,
    ).toBe(5_000);
  });

  it.each([401, 403, 404])(
    "stops polling after a permanent %s response",
    (status) => {
      const interval = refetchInterval();
      const error = Object.assign(new Error("Request failed"), { status });

      expect(interval).toBeTypeOf("function");
      expect(
        typeof interval === "function"
          ? interval({ state: { error } } as never)
          : interval,
      ).toBe(false);
    },
  );

  it("disables query retries", () => {
    renderHook(() => useChannelFeedMessages("channel-id"));

    expect(vi.mocked(useAuthenticatedQuery).mock.calls[0]?.[2]?.retry).toBe(
      false,
    );
  });
});
