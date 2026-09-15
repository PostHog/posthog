import type { AuthService } from "@posthog/core/auth/auth";
import { describe, expect, it, vi } from "vitest";
import { FeedbackSubmissionService } from "./feedbackAttachmentService";

describe("FeedbackSubmissionService", () => {
  it("submits feedback and images through the authenticated feedback endpoint", async () => {
    const authenticatedFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          accepted: true,
          response_id: "00000000-0000-0000-0000-000000000001",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );
    const authService = {
      getValidAccessToken: vi
        .fn()
        .mockResolvedValue({ apiHost: "https://app.example.com" }),
      authenticatedFetch,
    } as unknown as AuthService;
    const service = new FeedbackSubmissionService(authService);

    await expect(
      service.submitFeedback({
        response: "The page did not load",
        source: "Generic (Leave feedback button)",
        feedbackView: "task-detail",
        feedbackTaskId: "task-123",
        appVersion: "1.2.3",
        screenshot: {
          name: "screenshot.jpg",
          dataUrl: "data:image/jpeg;base64,aGVsbG8=",
        },
        images: [
          {
            name: "state.png",
            dataUrl: "data:image/png;base64,aGVsbG8=",
          },
        ],
      }),
    ).resolves.toBeUndefined();

    const [, url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("https://app.example.com/api/desktop_feedback/");
    expect(init).toMatchObject({ method: "POST" });
    const form = init.body as FormData;
    expect(form.get("response")).toBe("The page did not load");
    expect(form.get("feedback_task_id")).toBe("task-123");
    expect(form.get("app_version")).toBe("1.2.3");
    const image = form.get("image_1");
    expect(image).toBeInstanceOf(File);
    expect(image).toMatchObject({ name: "state.png", type: "image/png" });
    expect(form.get("screenshot")).toMatchObject({
      name: "screenshot.jpg",
      type: "image/jpeg",
    });
  });

  it.each([
    {
      response: new Response("unavailable", { status: 503 }),
      error: "Could not send feedback (503)",
    },
    {
      response: new Response(JSON.stringify({ accepted: false }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
      error: "Feedback response was not accepted",
    },
  ])(
    "rejects when the server does not accept feedback",
    async ({ response, error }) => {
      const authService = {
        getValidAccessToken: vi
          .fn()
          .mockResolvedValue({ apiHost: "https://app.example.com" }),
        authenticatedFetch: vi.fn().mockResolvedValue(response),
      } as unknown as AuthService;
      const service = new FeedbackSubmissionService(authService);

      await expect(
        service.submitFeedback({
          response: "Example feedback",
          source: "Generic (Leave feedback button)",
          feedbackView: "home",
          images: [],
        }),
      ).rejects.toThrow(error);
    },
  );
});
