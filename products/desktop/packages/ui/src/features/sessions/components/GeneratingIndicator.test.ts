import { formatDuration } from "@posthog/ui/features/sessions/components/GeneratingIndicator";
import { describe, expect, it } from "vitest";

describe("formatDuration", () => {
  it("formats sub-minute durations with configurable precision", () => {
    expect(formatDuration(12_340)).toBe("12.34s");
    expect(formatDuration(12_340, 1)).toBe("12.3s");
  });

  it("preserves minute formatting", () => {
    expect(formatDuration(62_340)).toBe("1m 02s");
    expect(formatDuration(62_340, 1)).toBe("1m 02s");
  });
});
