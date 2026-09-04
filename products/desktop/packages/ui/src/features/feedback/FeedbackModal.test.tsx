import type { IFeedbackContext } from "@posthog/platform/feedback-context";
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

const contextClient: IFeedbackContext = {
  captureScreenshot: vi.fn(),
  readRecentLogs: vi.fn(),
};

function renderModal(mode: FeedbackModalMode | null, onFinished = vi.fn()) {
  render(
    <FeedbackModal
      mode={mode}
      onFinished={onFinished}
      contextClient={contextClient}
    />,
  );
  return onFinished;
}

describe("FeedbackModal", () => {
  beforeEach(() => {
    captureSurveyResponse.mockReset();
    toastSuccess.mockReset();
    vi.mocked(contextClient.captureScreenshot).mockReset();
    vi.mocked(contextClient.captureScreenshot).mockResolvedValue(null);
    vi.mocked(contextClient.readRecentLogs).mockReset();
    vi.mocked(contextClient.readRecentLogs).mockResolvedValue(null);
  });

  it("asks for Desktop feedback", async () => {
    renderModal("feedback");
    expect(
      await screen.findByText("What should we improve in PostHog Desktop?"),
    ).toBeInTheDocument();
  });

  it.each([
    { mode: "posthog-web" as const, expected: "Skip", missing: "Cancel" },
    { mode: "feedback" as const, expected: "Cancel", missing: "Skip" },
  ])(
    "shows the $expected secondary button in $mode mode",
    async ({ mode, expected, missing }) => {
      renderModal(mode);
      expect(
        await screen.findByRole("button", { name: expected }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: missing }),
      ).not.toBeInTheDocument();
    },
  );

  it("disables submit until text is entered", async () => {
    const user = userEvent.setup();
    renderModal("feedback");
    const submit = await screen.findByRole("button", {
      name: "Send feedback",
    });
    expect(submit).toHaveAttribute("aria-disabled", "true");

    await user.type(screen.getByPlaceholderText("Share your feedback"), "hi");
    expect(submit).not.toHaveAttribute("aria-disabled", "true");
  });

  it("captures the response with its source and safe page context", async () => {
    const user = userEvent.setup();
    vi.mocked(contextClient.captureScreenshot).mockResolvedValue(
      "data:image/jpeg;base64,c2NyZWVuc2hvdA==",
    );
    const onFinished = renderModal("feedback");

    await user.type(
      await screen.findByPlaceholderText("Share your feedback"),
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
          feedback_screenshot_data_url:
            "data:image/jpeg;base64,c2NyZWVuc2hvdA==",
        },
      }),
    );
    expect(contextClient.readRecentLogs).not.toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith("Feedback sent");
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("submits opt-in logs and omits a removed screenshot", async () => {
    const user = userEvent.setup();
    vi.mocked(contextClient.captureScreenshot).mockResolvedValue(
      "data:image/jpeg;base64,c2NyZWVuc2hvdA==",
    );
    vi.mocked(contextClient.readRecentLogs).mockResolvedValue(
      "[info] app ready",
    );
    renderModal("feedback");

    expect(
      await screen.findByAltText(
        "App screenshot captured before this dialog opened",
      ),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Attach recent app logs" }),
    );
    expect(await screen.findByLabelText("Recent app logs")).toHaveValue(
      "[info] app ready",
    );
    await user.click(screen.getAllByRole("button", { name: "Remove" })[0]);
    await user.type(
      screen.getByPlaceholderText("Share your feedback"),
      "The page stopped updating",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    expect(captureSurveyResponse).toHaveBeenCalledWith(
      expect.objectContaining({
        additionalProperties: expect.not.objectContaining({
          feedback_screenshot_data_url: expect.anything(),
        }),
      }),
    );
    expect(captureSurveyResponse).toHaveBeenCalledWith(
      expect.objectContaining({
        additionalProperties: expect.objectContaining({
          feedback_app_logs: "[info] app ready",
        }),
      }),
    );
  });

  it("finishes without capturing when skipped", async () => {
    const user = userEvent.setup();
    const onFinished = renderModal("posthog-web");

    await user.click(screen.getByRole("button", { name: "Skip" }));

    expect(captureSurveyResponse).not.toHaveBeenCalled();
    expect(onFinished).toHaveBeenCalledTimes(1);
  });
});
