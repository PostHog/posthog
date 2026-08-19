import {
  formatDuration,
  GeneratingIndicator,
} from "@posthog/ui/features/sessions/components/GeneratingIndicator";
import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("GeneratingIndicator", () => {
  afterEach(() => vi.useRealTimers());

  it("formats sub-minute durations with configurable precision", () => {
    expect(formatDuration(12_340)).toBe("12.34s");
    expect(formatDuration(12_340, 1)).toBe("12.3s");
  });

  it("preserves minute formatting", () => {
    expect(formatDuration(62_340)).toBe("1m 02s");
    expect(formatDuration(62_340, 1)).toBe("1m 02s");
  });
  it("shows elapsed time immediately when remounted", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-28T12:00:30Z"));

    render(
      createElement(GeneratingIndicator, { startedAt: Date.now() - 30_000 }),
    );

    expect(screen.getByText("30s")).toBeInTheDocument();
  });
});
