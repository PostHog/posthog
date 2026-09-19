import type { SignalUserAutonomyConfig } from "@posthog/shared/types";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUpdateConfig = vi.hoisted(() => vi.fn());
const mockToastError = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => ({
    updateSignalUserAutonomyConfig: mockUpdateConfig,
  }),
  useOptionalAuthenticatedClient: () => ({
    updateSignalUserAutonomyConfig: mockUpdateConfig,
  }),
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: mockToastError },
}));

import { useSignalUserAutonomyMutations } from "./useSignalUserAutonomyMutations";

const QUERY_KEY = ["signals", "user-autonomy-config"];

const EXISTING: SignalUserAutonomyConfig = {
  autostart_priority: "P2",
  slack_notification_integration_id: 7,
  slack_notification_channel: "C123|#self-driving",
  slack_notification_min_priority: "P1",
  github_assign_on_pull_request: false,
};

function renderMutations() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  queryClient.setQueryData(QUERY_KEY, EXISTING);
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return {
    queryClient,
    ...renderHook(() => useSignalUserAutonomyMutations(), { wrapper }),
  };
}

describe("useSignalUserAutonomyMutations", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends only the GitHub field, so autostart and Slack settings survive", async () => {
    mockUpdateConfig.mockResolvedValue({
      ...EXISTING,
      github_assign_on_pull_request: true,
    });
    const { queryClient, result } = renderMutations();

    act(() => result.current.handleUpdateGithubAssignment(true));

    await waitFor(() =>
      expect(mockUpdateConfig).toHaveBeenCalledWith({
        github_assign_on_pull_request: true,
      }),
    );
    await waitFor(() =>
      expect(
        queryClient.getQueryData<SignalUserAutonomyConfig>(QUERY_KEY),
      ).toEqual({ ...EXISTING, github_assign_on_pull_request: true }),
    );
  });

  it("restores the whole previous config when the update fails", async () => {
    mockUpdateConfig.mockRejectedValue(new Error("nope"));
    const { queryClient, result } = renderMutations();

    act(() => result.current.handleUpdateGithubAssignment(true));

    await waitFor(() => expect(mockToastError).toHaveBeenCalledWith("nope"));
    expect(queryClient.getQueryData(QUERY_KEY)).toEqual(EXISTING);
  });
});
