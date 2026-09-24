import type { FeedbackSubmissionInput } from "@posthog/platform/feedback-context";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  captureException,
  getAnalyticsSessionId,
  toastError,
  toastSuccess,
  toastWarning,
} = vi.hoisted(() => ({
  captureException: vi.fn(),
  getAnalyticsSessionId: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
  toastWarning: vi.fn(),
}));

vi.mock("@posthog/ui/shell/analytics", () => ({
  captureException,
  getAnalyticsSessionId,
}));
vi.mock("@posthog/ui/primitives/toast", () => ({
  toast: { error: toastError, success: toastSuccess, warning: toastWarning },
}));
vi.mock("@posthog/ui/router/useAppView", () => ({
  getAppViewSnapshot: () => ({ type: "task-detail", taskId: "task-123" }),
}));

import { FeedbackModal, type FeedbackModalMode } from "./FeedbackModal";

const pngBytes = new Uint8Array([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
]);

const readRecentLogs = vi.fn<() => Promise<string | null>>();
const captureScreenshot = vi.fn<() => Promise<string | null>>();
const submitFeedback =
  vi.fn<(input: FeedbackSubmissionInput) => Promise<void>>();

async function renderModal(
  mode: FeedbackModalMode | null,
  onFinished = vi.fn(),
) {
  render(
    <FeedbackModal
      mode={mode}
      onFinished={onFinished}
      contextClient={{ captureScreenshot, readRecentLogs, submitFeedback }}
    />,
  );
  if (mode !== null) await screen.findByRole("dialog");
  return onFinished;
}

describe("FeedbackModal", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "createImageBitmap",
      vi.fn().mockResolvedValue({ width: 2, height: 2, close: vi.fn() }),
    );
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      fillStyle: "",
      fillRect: vi.fn(),
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
      (callback) => callback(new Blob(["re-encoded"], { type: "image/jpeg" })),
    );
    captureException.mockReset();
    getAnalyticsSessionId.mockReset();
    getAnalyticsSessionId.mockReturnValue(
      "00000000-0000-0000-0000-000000000001",
    );
    readRecentLogs.mockReset();
    readRecentLogs.mockResolvedValue("[info] Example log");
    captureScreenshot.mockReset();
    captureScreenshot.mockResolvedValue(
      "data:image/jpeg;base64,c2NyZWVuc2hvdA==",
    );
    submitFeedback.mockReset();
    submitFeedback.mockResolvedValue();
    toastError.mockReset();
    toastSuccess.mockReset();
    toastWarning.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("asks for specific Desktop feedback", async () => {
    await renderModal("feedback");
    expect(
      screen.getByText("What should we improve in PostHog Desktop?"),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("What happened, and what did you expect?"),
    ).toBeInTheDocument();
  });

  it("keeps the dialog out of session replay", async () => {
    await renderModal("feedback");
    expect(screen.getByRole("dialog")).toHaveClass("ph-no-capture");
  });

  it.each([
    { label: "Bug", value: "bug" },
    { label: "Feature", value: "feature" },
    { label: "General", value: "general" },
  ])("sends the selected $label feedback type", async ({ label, value }) => {
    const user = userEvent.setup();
    await renderModal("feedback");
    const selector = screen.getByRole("combobox", { name: "Feedback type" });
    expect(screen.getByLabelText("Feedback type")).toBe(selector);
    expect(selector).toHaveTextContent("General");
    await user.click(selector);
    // The select mounts its popup in a portal, so the option arrives a frame
    // after the click. `getByRole` does not retry, and a loaded CI runner loses
    // that race.
    await user.click(await screen.findByRole("option", { name: label }));
    await user.type(
      screen.getByPlaceholderText("What happened, and what did you expect?"),
      "Example feedback",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(submitFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ feedbackType: value }),
    );
  });

  it("does not ask for a type before opening PostHog web", async () => {
    const user = userEvent.setup();
    await renderModal("posthog-web");
    expect(
      screen.queryByRole("combobox", { name: "Feedback type" }),
    ).not.toBeInTheDocument();
    await user.type(
      screen.getByPlaceholderText("What are you looking for in PostHog web?"),
      "Example feedback",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(submitFeedback.mock.calls[0][0]).not.toHaveProperty("feedbackType");
  });

  it.each([
    { mode: "posthog-web" as const, expected: "Skip", missing: "Cancel" },
    { mode: "feedback" as const, expected: "Cancel", missing: "Skip" },
  ])(
    "shows the $expected secondary button in $mode mode",
    async ({ mode, expected, missing }) => {
      await renderModal(mode);
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
    await renderModal("feedback");
    const submit = screen.getByRole("button", { name: "Send feedback" });
    expect(submit).toBeDisabled();

    await user.type(
      screen.getByPlaceholderText("What happened, and what did you expect?"),
      "hi",
    );
    expect(submit).toBeEnabled();
  });

  it("submits the response with its source and page context", async () => {
    const user = userEvent.setup();
    const onFinished = await renderModal("feedback");
    const logsCheckbox = screen.getByRole("checkbox", {
      name: "Include recent app logs",
    });

    expect(logsCheckbox).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "View app logs" }));
    expect(await screen.findByLabelText("Recent app logs")).toHaveValue(
      "[info] Example log",
    );
    expect(logsCheckbox).not.toBeChecked();

    await user.type(
      screen.getByPlaceholderText("What happened, and what did you expect?"),
      "  improve search  ",
    );
    await user.keyboard("{Meta>}{Enter}{/Meta}");

    expect(submitFeedback).toHaveBeenCalledWith({
      response: "improve search",
      source: "Generic (Leave feedback button)",
      feedbackType: "general",
      feedbackView: "task-detail",
      feedbackTaskId: "task-123",
      sessionId: "00000000-0000-0000-0000-000000000001",
      images: [],
    });
    expect(toastSuccess).toHaveBeenCalledWith("Feedback sent");
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it.each([
    { input: "upload", type: "image/png", bytes: pngBytes },
    { input: "paste", type: "image/png", bytes: pngBytes },
    { input: "paste PNG without MIME type", type: "", bytes: pngBytes },
    {
      input: "paste JPEG without MIME type",
      type: "",
      bytes: new Uint8Array([0xff, 0xd8, 0xff]),
    },
    {
      input: "paste WebP without MIME type",
      type: "",
      bytes: new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 69, 66, 80]),
    },
  ])(
    "sends selected logs, screenshot, and images from $input together",
    async ({ input, type, bytes }) => {
      const user = userEvent.setup();
      await renderModal("feedback");

      expect(readRecentLogs).not.toHaveBeenCalled();
      expect(captureScreenshot).toHaveBeenCalledTimes(1);
      expect(
        screen.getByRole("checkbox", {
          name: "Include screenshot of this window",
        }),
      ).not.toBeChecked();
      await user.click(
        screen.getByRole("checkbox", {
          name: "Include screenshot of this window",
        }),
      );
      let resolveLogs: (value: string | null) => void = () => {};
      readRecentLogs.mockImplementation(
        () =>
          new Promise((resolve) => {
            resolveLogs = resolve;
          }),
      );
      const logsCheckbox = screen.getByRole("checkbox", {
        name: "Include recent app logs",
      });
      await user.click(logsCheckbox);
      expect(readRecentLogs).toHaveBeenCalledTimes(1);
      expect(logsCheckbox).toBeChecked();
      expect(logsCheckbox).toBeEnabled();
      expect(
        screen.queryByText("Loading recent app logs"),
      ).not.toBeInTheDocument();
      resolveLogs("[info] Example log");
      await screen.findByRole("button", { name: "View app logs" });

      const image = new File([bytes], "feedback.png", {
        type,
      });
      if (input === "upload") {
        await user.upload(
          screen.getByLabelText("Choose feedback images"),
          image,
        );
      } else {
        fireEvent.paste(
          screen.getByPlaceholderText(
            "What happened, and what did you expect?",
          ),
          {
            clipboardData: { files: [image], getData: () => "" },
          },
        );
      }
      expect(await screen.findByText("1 attached")).toBeInTheDocument();
      expect(
        await screen.findByRole("img", { name: "Attachment feedback.png" }),
      ).toBeInTheDocument();

      await user.type(
        screen.getByPlaceholderText("What happened, and what did you expect?"),
        "The page did not load",
      );
      await user.click(screen.getByRole("button", { name: "Send feedback" }));

      await waitFor(() => expect(submitFeedback).toHaveBeenCalled());
      expect(submitFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          feedbackAppLogs: "[info] Example log",
          screenshot: {
            name: "posthog-desktop-screenshot.jpg",
            dataUrl: "data:image/jpeg;base64,c2NyZWVuc2hvdA==",
          },
          images: [
            expect.objectContaining({
              name: "feedback.png",
              dataUrl: expect.stringMatching(/^data:image\/jpeg;base64,/),
            }),
          ],
        }),
      );
    },
  );

  it("keeps text paste and lets users remove pasted images", async () => {
    const user = userEvent.setup();
    await renderModal("feedback");
    const textarea = screen.getByPlaceholderText(
      "What happened, and what did you expect?",
    );
    await user.click(textarea);
    await user.paste("Example feedback");
    expect(textarea).toHaveValue("Example feedback");
    const accepted = fireEvent.paste(textarea, {
      clipboardData: {
        files: [new File([pngBytes], "pasted.png", { type: "image/png" })],
        getData: () => "More context",
      },
    });
    expect(accepted).toBe(true);
    await user.click(
      await screen.findByRole("button", { name: "Remove pasted.png" }),
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));
    expect(submitFeedback).toHaveBeenCalledWith(
      expect.objectContaining({ images: [] }),
    );
  });

  it("shares the image limit between file selection and paste", async () => {
    const user = userEvent.setup();
    await renderModal("feedback");
    await user.upload(
      screen.getByLabelText("Choose feedback images"),
      new File([pngBytes], "selected.png", { type: "image/png" }),
    );
    await screen.findByText("1 attached");
    fireEvent.paste(
      screen.getByPlaceholderText("What happened, and what did you expect?"),
      {
        clipboardData: {
          files: ["second.png", "third.png"].map(
            (name) => new File([pngBytes], name, { type: "image/png" }),
          ),
          getData: () => "",
        },
      },
    );
    await screen.findByText("2 attached");
    expect(
      screen.queryByRole("img", { name: "Attachment third.png" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    { type: "image/gif", bytes: pngBytes },
    { type: "image/jpeg", bytes: pngBytes },
    { type: "", bytes: new Uint8Array([1, 2, 3]) },
  ])(
    "blocks submission during image loading and rejects invalid images ($type)",
    async ({ type, bytes }) => {
      const user = userEvent.setup();
      let finish: BlobCallback = () => {};
      vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
        (callback) => {
          finish = callback;
        },
      );
      await renderModal("feedback");
      const textarea = screen.getByPlaceholderText(
        "What happened, and what did you expect?",
      );
      await user.type(textarea, "Example feedback");
      fireEvent.paste(textarea, {
        clipboardData: {
          files: [new File([pngBytes], "pasted.png", { type: "image/png" })],
          getData: () => "",
        },
      });
      await waitFor(() =>
        expect(HTMLCanvasElement.prototype.toBlob).toHaveBeenCalled(),
      );
      expect(
        screen.getByRole("button", { name: "Send feedback" }),
      ).toBeDisabled();
      await user.keyboard("{Meta>}{Enter}{/Meta}");
      expect(submitFeedback).not.toHaveBeenCalled();
      fireEvent.paste(textarea, {
        clipboardData: {
          files: [new File([pngBytes], "second.png", { type: "image/png" })],
          getData: () => "",
        },
      });
      expect(toastWarning).toHaveBeenCalledWith(
        "An image is still loading. Wait, then paste it again.",
      );
      finish(new Blob(["image"], { type: "image/jpeg" }));
      await screen.findByText("1 attached");
      fireEvent.paste(textarea, {
        clipboardData: {
          files: [new File([bytes], "unsupported.gif", { type })],
          getData: () => "",
        },
      });
      await waitFor(() =>
        expect(toastError).toHaveBeenCalledWith(
          "Choose a JPEG, PNG, or WebP image.",
        ),
      );
      expect(
        screen.getByRole("button", { name: "Send feedback" }),
      ).toBeEnabled();
    },
  );

  it("does not add logs after they are unchecked while loading", async () => {
    const user = userEvent.setup();
    let resolveLogs: (value: string | null) => void = () => {};
    readRecentLogs.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLogs = resolve;
        }),
    );
    await renderModal("feedback");

    const logsCheckbox = screen.getByRole("checkbox", {
      name: "Include recent app logs",
    });
    await user.click(logsCheckbox);
    await user.click(logsCheckbox);
    resolveLogs("[info] Example log");

    await waitFor(() => expect(logsCheckbox).not.toBeChecked());
    expect(
      screen.getByRole("button", { name: "View app logs" }),
    ).toBeInTheDocument();
  });

  it("finishes without capturing when skipped", async () => {
    const user = userEvent.setup();
    const onFinished = await renderModal("posthog-web");
    await user.click(screen.getByRole("button", { name: "Skip" }));
    expect(submitFeedback).not.toHaveBeenCalled();
    expect(onFinished).toHaveBeenCalledTimes(1);
  });

  it("keeps the form open when the server does not accept feedback", async () => {
    const user = userEvent.setup();
    const onFinished = await renderModal("feedback");
    submitFeedback.mockRejectedValue(new Error("Unavailable"));

    await user.type(
      screen.getByPlaceholderText("What happened, and what did you expect?"),
      "Example feedback",
    );
    await user.click(screen.getByRole("button", { name: "Send feedback" }));

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        "Could not send feedback. Try again.",
      ),
    );
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(onFinished).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});
