import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("inversify", () => ({
  injectable: () => (target: unknown) => target,
  inject: () => () => undefined,
}));

vi.mock("@posthog/core/feedback/feedbackAttachmentService", () => ({
  FEEDBACK_SUBMISSION_SERVICE: Symbol.for(
    "posthog.core.feedback.submissionService",
  ),
}));

vi.mock("../utils/env", () => ({ getAppVersion: () => "1.2.3" }));

vi.mock("../utils/logger", () => ({
  getLogFilePath: () => "/tmp/posthog-desktop-test.log",
}));

import { ElectronFeedbackContext } from "./electron-feedback-context";

function makeContext(capturePage: () => Promise<unknown>) {
  const submissionService = { submitFeedback: vi.fn() };
  const mainWindow = {
    getBrowserWindow: () => ({ webContents: { capturePage } }),
  };
  return new ElectronFeedbackContext(
    submissionService as never,
    mainWindow as never,
  );
}

const jpegImage = {
  isEmpty: () => false,
  getSize: () => ({ width: 1_000, height: 800 }),
  resize: () => ({ toJPEG: () => Buffer.from("jpeg") }),
};

describe("ElectronFeedbackContext.captureScreenshot", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the captured window as a JPEG data URL", async () => {
    const context = makeContext(() => Promise.resolve(jpegImage));

    await expect(context.captureScreenshot()).resolves.toBe(
      `data:image/jpeg;base64,${Buffer.from("jpeg").toString("base64")}`,
    );
  });

  it("gives up on a capture that never settles", async () => {
    vi.useFakeTimers();
    const context = makeContext(() => new Promise(() => {}));

    const pending = context.captureScreenshot();
    await vi.advanceTimersByTimeAsync(2_000);

    await expect(pending).resolves.toBeNull();
  });
});
