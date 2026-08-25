import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useAuthUiStateStore } from "./authUiStateStore";
import { useOAuthFlow } from "./useOAuthFlow";

const loginMutation = {
  mutate: vi.fn(),
  reset: vi.fn(),
  isPending: false,
  error: null,
};

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({ oauth: { cancelFlow: { mutate: vi.fn() } } }),
}));

vi.mock("./useAuthMutations", () => ({
  useLoginMutation: () => loginMutation,
}));

describe("useOAuthFlow", () => {
  afterEach(() => {
    loginMutation.mutate.mockReset();
    loginMutation.reset.mockReset();
    useAuthUiStateStore.setState({ selectedRegion: null, staleRegion: null });
  });

  it("publishes the selected region before OAuth completes", () => {
    const { result } = renderHook(() => useOAuthFlow());

    expect(useAuthUiStateStore.getState().selectedRegion).toBe("us");

    act(() => result.current.handleRegionChange("eu"));

    expect(useAuthUiStateStore.getState().selectedRegion).toBe("eu");
  });
});
