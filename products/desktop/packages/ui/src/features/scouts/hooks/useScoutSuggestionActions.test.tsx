import type {
  ScoutConfig,
  ScoutSuggestionItem,
  ScoutSuggestionSet,
} from "@posthog/api-client/posthog-client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const client = vi.hoisted(() => ({
  dismissScoutSuggestion: vi.fn(),
  createScout: vi.fn(),
  updateScoutConfig: vi.fn(),
  refreshScoutSuggestions: vi.fn(),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: (
    select: (state: { currentProjectId: number | null }) => unknown,
  ) => select({ currentProjectId: 42 }),
}));
vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useAuthenticatedClient: () => client,
}));
const toastError = vi.hoisted(() => vi.fn());
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError, success: vi.fn() },
}));
vi.mock("@posthog/ui/shell/analytics", () => ({ track: vi.fn() }));

import { ScoutRequestError } from "@posthog/api-client/posthog-client";
import { scoutQueryKeys } from "./scoutQueryKeys";
import { useScoutSuggestionActions } from "./useScoutSuggestionActions";

const CANONICAL: ScoutSuggestionItem = {
  id: "suggestion-canonical",
  kind: "canonical",
  skill_name: "signals-scout-error-tracking",
  title: "Sweep error tracking",
  why_here: "Errors spiked twice last week.",
  description: "",
  draft_body: "",
  proposed_config: {
    run_cron_schedule: null,
    run_interval_minutes: null,
    emit: true,
  },
  gap: false,
  confidence: "high",
};
const CUSTOM: ScoutSuggestionItem = {
  ...CANONICAL,
  id: "suggestion-custom",
  kind: "custom",
  skill_name: "signals-scout-checkout-funnel",
  description: "Watches checkout conversion.",
  draft_body: "# Checkout funnel",
};
const CONFIG = {
  id: "config-1",
  skill_name: "signals-scout-error-tracking",
  enabled: false,
  emit: true,
  run_interval_minutes: 1440,
} as ScoutConfig;
const SET: ScoutSuggestionSet = {
  status: "fresh",
  generated_at: "2026-09-05T10:00:00Z",
  model: "",
  fleet_snapshot: [],
  items: [CANONICAL, CUSTOM],
};

let queryClient: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function renderActions(suggestionSet: ScoutSuggestionSet | null = SET) {
  return renderHook(
    () => useScoutSuggestionActions({ surface: "strip", suggestionSet }),
    { wrapper },
  );
}

describe("useScoutSuggestionActions", () => {
  beforeEach(() => {
    for (const fn of Object.values(client)) fn.mockReset();
    toastError.mockReset();
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    queryClient.setQueryData(scoutQueryKeys.configs(42), [CONFIG]);
  });

  it("turns a canonical pick on through its existing config", async () => {
    client.updateScoutConfig.mockResolvedValue(CONFIG);
    const { result } = renderActions();

    await act(() => result.current.activate(CANONICAL));

    expect(client.updateScoutConfig).toHaveBeenCalledWith(42, "config-1", {
      enabled: true,
    });
    expect(result.current.hiddenIds).toEqual([CANONICAL.id]);
  });

  it("creates a custom pick from its draft, carrying the suggestion id", async () => {
    client.createScout.mockResolvedValue({ created: true });
    const { result } = renderActions();

    await act(() => result.current.activate(CUSTOM));

    expect(client.createScout).toHaveBeenCalledWith(
      42,
      expect.objectContaining({
        name: CUSTOM.skill_name,
        body: CUSTOM.draft_body,
        suggestion_id: CUSTOM.id,
      }),
    );
  });

  // A pick that stays hidden after a failed request reads as a press that worked.
  it("puts a pick back when its creation fails", async () => {
    client.createScout.mockRejectedValue(
      new ScoutRequestError(400, "", "Bad Request", "That name is taken."),
    );
    const { result } = renderActions();

    await act(() => result.current.activate(CUSTOM));

    expect(result.current.hiddenIds).toEqual([]);
    expect(toastError).toHaveBeenCalledWith("That name is taken.");
  });

  it("puts a pick back when its dismissal fails", async () => {
    client.dismissScoutSuggestion.mockRejectedValue(
      new ScoutRequestError(500, "", "Server Error"),
    );
    const { result } = renderActions();

    await act(() => result.current.dismiss(CUSTOM));

    expect(result.current.hiddenIds).toEqual([]);
  });

  it("keeps a dismissed pick hidden until the next read", async () => {
    client.dismissScoutSuggestion.mockResolvedValue(CUSTOM);
    const { result } = renderActions();

    await act(() => result.current.dismiss(CUSTOM));

    expect(result.current.hiddenIds).toEqual([CUSTOM.id]);
  });

  it("waits out a scan that is already running rather than reporting a failure", async () => {
    client.refreshScoutSuggestions.mockRejectedValue(
      new ScoutRequestError(409, "", "Conflict"),
    );
    const { result } = renderActions();

    await act(() => result.current.refresh());

    expect(result.current.isScanning).toBe(true);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("shows the endpoint's own reason when a refresh is refused", async () => {
    client.refreshScoutSuggestions.mockRejectedValue(
      new ScoutRequestError(
        429,
        "",
        "Too Many Requests",
        "Try again tomorrow.",
      ),
    );
    const { result } = renderActions();

    await act(() => result.current.refresh());

    expect(result.current.isScanning).toBe(false);
    expect(toastError).toHaveBeenCalledWith("Try again tomorrow.");
  });

  it("ends the wait once a newer batch lands", async () => {
    client.refreshScoutSuggestions.mockResolvedValue({ workflow_id: "wf-1" });
    const { result, rerender } = renderHook(
      ({ set }: { set: ScoutSuggestionSet }) =>
        useScoutSuggestionActions({ surface: "strip", suggestionSet: set }),
      { wrapper, initialProps: { set: SET } },
    );

    await act(() => result.current.refresh());
    expect(result.current.isScanning).toBe(true);

    rerender({ set: { ...SET, generated_at: "2026-09-05T12:00:00Z" } });

    await waitFor(() => expect(result.current.isScanning).toBe(false));
  });
});
