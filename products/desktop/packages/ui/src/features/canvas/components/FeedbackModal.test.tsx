import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { captureSurveyResponse } = vi.hoisted(() => ({
  captureSurveyResponse: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ captureSurveyResponse }));

import { FeedbackModal, type FeedbackModalMode } from "./FeedbackModal";

function renderModal(mode: FeedbackModalMode | null, onFinished = vi.fn()) {
  render(
    <Theme>
      <FeedbackModal mode={mode} onFinished={onFinished} />
    </Theme>,
  );
  return onFinished;
}

describe("FeedbackModal", () => {
  beforeEach(() => {
    captureSurveyResponse.mockReset();
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
    // The quill Button signals disabled state via aria-disabled, not the native attr.
    expect(submit).toHaveAttribute("aria-disabled", "true");

    await user.type(screen.getByPlaceholderText("Share your feedback"), "hi");
    expect(submit).not.toHaveAttribute("aria-disabled", "true");
  });

  it("captures the trimmed response with its source and finishes on submit", async () => {
    const user = userEvent.setup();
    const onFinished = renderModal("posthog-web");

    await user.type(
      screen.getByPlaceholderText("Share your feedback"),
      "  great work  ",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    expect(captureSurveyResponse).toHaveBeenCalledTimes(1);
    expect(captureSurveyResponse).toHaveBeenCalledWith(
      expect.objectContaining({
        responses: [
          expect.objectContaining({ response: "great work" }),
          expect.objectContaining({ response: "Visiting PostHog web" }),
        ],
      }),
    );
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
