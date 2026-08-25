import type { SpendSnapshot } from "@posthog/ui/features/billing/useSpendTotals";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const spendTotals = vi.hoisted(() => ({
  value: null as SpendSnapshot | null,
}));
const toastMock = vi.hoisted(() => ({ warning: vi.fn(), dismiss: vi.fn() }));

vi.mock("@posthog/ui/features/billing/useSpendTotals", () => ({
  useSpendTotals: () => spendTotals.value,
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
});
