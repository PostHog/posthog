import { beforeEach, describe, expect, it } from "vitest";
import { useUsageLimitStore } from "./usageLimitStore";

describe("usageLimitStore", () => {
  beforeEach(() => {
    useUsageLimitStore.setState({
      isOpen: false,
      resetAt: null,
      cause: null,
    });
  });

  it("starts closed", () => {
    const state = useUsageLimitStore.getState();
    expect(state.isOpen).toBe(false);
  });

  it("show opens the modal with no context", () => {
    useUsageLimitStore.getState().show();
    const state = useUsageLimitStore.getState();
    expect(state.isOpen).toBe(true);
    expect(state.resetAt).toBeNull();
    expect(state.cause).toBeNull();
  });

  it("show stores the denial context when provided", () => {
    useUsageLimitStore.getState().show({
      resetAt: "2026-01-02T03:04:05Z",
      cause: "model_gate",
    });
    const state = useUsageLimitStore.getState();
    expect(state.isOpen).toBe(true);
    expect(state.resetAt).toBe("2026-01-02T03:04:05Z");
    expect(state.cause).toBe("model_gate");
  });

  it("hide closes the modal", () => {
    useUsageLimitStore.getState().show();
    useUsageLimitStore.getState().hide();
    expect(useUsageLimitStore.getState().isOpen).toBe(false);
  });
});
