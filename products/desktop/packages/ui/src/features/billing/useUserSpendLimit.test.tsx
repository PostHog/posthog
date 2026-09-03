import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  enabled: false,
  getUserSpendLimit: vi.fn(),
  setUserSpendLimit: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => ({
    getUserSpendLimit: mocks.getUserSpendLimit,
    setUserSpendLimit: mocks.setUserSpendLimit,
  }),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => mocks.enabled,
}));

import { useSetUserSpendLimit, useUserSpendLimit } from "./useUserSpendLimit";

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useUserSpendLimit", () => {
  beforeEach(() => {
    mocks.enabled = false;
    mocks.getUserSpendLimit.mockReset();
    mocks.setUserSpendLimit.mockReset();
    mocks.getUserSpendLimit.mockResolvedValue({
      available: true,
      limitUsd: null,
      windowSeconds: null,
    });
  });

  it("does not call the endpoint while its rollout flag is off", () => {
    renderHook(() => useUserSpendLimit(), { wrapper });

    expect(mocks.getUserSpendLimit).not.toHaveBeenCalled();
  });

  it("calls the endpoint when its rollout flag is on", async () => {
    mocks.enabled = true;

    renderHook(() => useUserSpendLimit(), { wrapper });

    await waitFor(() => expect(mocks.getUserSpendLimit).toHaveBeenCalledOnce());
  });

  it("does not write to the endpoint while its rollout flag is off", async () => {
    const { result } = renderHook(() => useSetUserSpendLimit(), { wrapper });

    await expect(
      result.current.mutateAsync({ limitUsd: 10, windowSeconds: 60 }),
    ).resolves.toEqual({
      available: false,
      limitUsd: null,
      windowSeconds: null,
    });

    expect(mocks.setUserSpendLimit).not.toHaveBeenCalled();
  });
});
