import { beforeEach, describe, expect, it, vi } from "vitest";
import { useFeedbackStore } from "./feedbackStore";

describe("feedbackStore", () => {
  beforeEach(() => {
    useFeedbackStore.setState({ mode: null, onFinished: null });
  });

  it("keeps the active flow when another entry point opens feedback", () => {
    const onFinished = vi.fn();
    useFeedbackStore.getState().open("posthog-web", onFinished);

    useFeedbackStore.getState().open();

    expect(useFeedbackStore.getState().mode).toBe("posthog-web");
    useFeedbackStore.getState().finish();
    expect(onFinished).toHaveBeenCalledOnce();
  });
});
