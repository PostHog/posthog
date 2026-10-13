import { CONTEXT_LAYER_FLAG } from "@posthog/shared";
import { renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useContextLayerFlag } from "./useContextLayerFlag";

const useFeatureFlag = vi.hoisted(() => vi.fn(() => false));

vi.mock("./useFeatureFlag", () => ({ useFeatureFlag }));

it("keeps the context layer disabled when its flag is off", () => {
  const { result } = renderHook(() => useContextLayerFlag());

  expect(result.current).toBe(false);
  expect(useFeatureFlag).toHaveBeenCalledWith(CONTEXT_LAYER_FLAG);
});
