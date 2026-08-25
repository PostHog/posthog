import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/inbox/hooks/useInboxSectionCounts", () => ({
  useInboxSectionCounts: () => ({
    decision: 3,
    decisionPr: 1,
    monitoring: 2,
    isLoading: false,
  }),
}));

import { useInboxReportCount } from "./useInboxReportCount";

describe("useInboxReportCount", () => {
  it("counts decision and monitoring reports", () => {
    const { result } = renderHook(() => useInboxReportCount());

    expect(result.current).toBe(5);
  });
});
