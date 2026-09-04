import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useDefaultAgentHarness } from "./useDefaultAgentHarness";

const useFeatureFlagPayload = vi.hoisted(() => vi.fn());

vi.mock("./useFeatureFlagPayload", () => ({ useFeatureFlagPayload }));

describe("useDefaultAgentHarness", () => {
  it.each([
    { label: "matches an acp payload", payload: "acp", expected: "acp" },
    { label: "matches a pi payload", payload: "pi", expected: "pi" },
    {
      label: "falls back to pi when the payload is missing",
      payload: undefined,
      expected: "pi",
    },
    {
      label: "falls back to pi for a payload outside the runtime enum",
      payload: "claude",
      expected: "pi",
    },
  ])("$label", ({ payload, expected }) => {
    useFeatureFlagPayload.mockReturnValue(payload);

    const { result } = renderHook(() => useDefaultAgentHarness());

    expect(result.current).toBe(expected);
  });
});
