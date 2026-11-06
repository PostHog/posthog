import type { SpendSnapshot } from "@posthog/ui/features/billing/useSpendTotals";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const spendTotals = vi.hoisted(() => ({
  value: null as SpendSnapshot | null,
}));
const toastMock = vi.hoisted(() => ({ warning: vi.fn(), dismiss: vi.fn() }));
const spendAvailable = vi.hoisted(() => ({ value: true }));

vi.mock("@posthog/ui/features/billing/useSpendTotals", () => ({
  useSpendTotals: () => spendTotals.value,
}));
vi.mock("@posthog/ui/features/billing/useUserSpendLimit", () => ({
  useSpendLimitAvailable: () => spendAvailable.value,
}));
vi.mock("../../primitives/toast", () => ({ toast: toastMock }));
vi.mock("@posthog/ui/features/settings/hooks/useOpenSettings", () => ({
  openSettings: vi.fn(),
}));

import { useSpendGuardrails } from "./useSpendGuardrails";

describe("useSpendGuardrails", () => {
  beforeEach(() => {
    toastMock.warning.mockClear();
    toastMock.dismiss.mockClear();
    spendAvailable.value = true;
    useSettingsStore.setState({
      spendLimits: {
        day: { warnUsd: null, stopUsd: null },
        month: { warnUsd: null, stopUsd: null },
      },
      spendNoticesSeen: {},
    });
  });

  it("dismisses the sticky stop notice once the stop line no longer applies", () => {
    useSettingsStore.setState({
      spendLimits: {
        day: { warnUsd: null, stopUsd: 50 },
        month: { warnUsd: null, stopUsd: null },
      },
    });
    spendTotals.value = { todayUsd: 60, monthUsd: 60, avgDailyUsd: 0 };

    renderHook(() => useSpendGuardrails());
    expect(toastMock.warning).toHaveBeenCalledWith(
      expect.stringContaining("stop line"),
      expect.objectContaining({ id: "spend-limit-day-stop" }),
    );

    toastMock.dismiss.mockClear();
    // Raise the stop above current spend: the crossing clears, so the notice
    // that still says the composer is paused must be dismissed.
    act(() => {
      useSettingsStore.setState({
        spendLimits: {
          day: { warnUsd: null, stopUsd: 100 },
          month: { warnUsd: null, stopUsd: null },
        },
      });
    });

    expect(toastMock.dismiss).toHaveBeenCalledWith("spend-limit-day-stop");
  });

  it("raises no stop and pauses nothing when availability is off, but the warn at the same threshold still fires", () => {
    useSettingsStore.setState({
      spendLimits: {
        day: { warnUsd: 50, stopUsd: 50 },
        month: { warnUsd: null, stopUsd: null },
      },
    });
    spendTotals.value = { todayUsd: 60, monthUsd: 60, avgDailyUsd: 0 };
    spendAvailable.value = false;

    renderHook(() => useSpendGuardrails());

    // The stored stop is inert while the deployment cannot hold it: no stop
    // toast fires, and the sticky stop id is never registered.
    const stopCalls = toastMock.warning.mock.calls.filter((call) =>
      String(call[0]).includes("stop line"),
    );
    expect(stopCalls).toHaveLength(0);
    expect(toastMock.dismiss).toHaveBeenCalledWith("spend-limit-day-stop");

    // The warn at the same threshold still fires.
    expect(toastMock.warning).toHaveBeenCalledWith(
      expect.stringContaining("passed $50.00"),
      expect.objectContaining({ id: "spend-limit-day-warn" }),
    );
  });
});
