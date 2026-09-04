import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { captureSurveyResponse, toastSuccess } = vi.hoisted(() => ({
  captureSurveyResponse: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ captureSurveyResponse }));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { success: toastSuccess },
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  getAppViewSnapshot: () => ({ type: "task-detail", taskId: "task-123" }),
}));

import { FeedbackModal, type FeedbackModalMode } from "./FeedbackModal";

function renderModal(mode: FeedbackModalMode | null, onFinished = vi.fn()) {
  render(<FeedbackModal mode={mode} onFinished={onFinished} />);
  return onFinished;
}

describe("FeedbackModal", () => {
  beforeEach(() => {
    captureSurveyResponse.mockReset();
    toastSuccess.mockReset();
  });

  it("asks for Desktop feedback", () => {
    renderModal("feedback");
    expect(
      screen.getByText("What should we improve in PostHog Desktop?"),
    ).toBeInTheDocument();
  });

  it.each([
    { mode: "posthog-web" as const, expected: "Skip", missing: "Cancel" },
    { mode: "feedback" as const, expected: "Cancel", missing: "Skip" },
  ])(
    "shows the $expected secondary button in $mode mode",
    ({ mode, expected, missing }) => {
      renderModal(mode);
      expect(
        screen.getByRole("button", { name: expected }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: missing }),
      ).not.toBeInTheDocument();
    },
  );

  it("disables submit until text is entered", async () => {
    const user = userEvent.setup();
    renderModal("feedback");
    const submit = screen.getByRole("button", { name: "Send feedback" });
    expect(submit).toHaveAttribute("aria-disabled", "true");

    await user.type(screen.getByPlaceholderText("Share your feedback"), "hi");
    expect(submit).not.toHaveAttribute("aria-disabled", "true");
  });

  it("captures the response with its source and safe page context", async () => {
    const user = userEvent.setup();
    const onFinished = renderModal("feedback");

    await user.type(
      screen.getByPlaceholderText("Share your feedback"),
      "  improve search  ",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    expect(captureSurveyResponse).toHaveBeenCalledWith(
      expect.objectContaining({
        responses: [
          expect.objectContaining({ response: "improve search" }),
          expect.objectContaining({
            response: "Generic (Leave feedback button)",
          }),
        ],
        additionalProperties: {
          feedback_view: "task-detail",
          feedback_task_id: "task-123",
        },
      }),
    );
    expect(toastSuccess).toHaveBeenCalledWith("Feedback sent");
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("finishes without capturing when skipped", async () => {
    const user = userEvent.setup();
    const onFinished = renderModal("posthog-web");

    await user.click(screen.getByRole("button", { name: "Skip" }));

    expect(captureSurveyResponse).not.toHaveBeenCalled();
    expect(onFinished).toHaveBeenCalledTimes(1);
  });
});
