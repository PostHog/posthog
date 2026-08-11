import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import { SessionService } from "./sessionService";

describe("SessionService resource comments", () => {
  it("keeps successful targets when one target fails", async () => {
    const service = Object.create(SessionService.prototype) as SessionService;
    const successfulComment = { id: "comment-2" } as ResourceComment;
    const getResourceComments = vi
      .fn()
      .mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce([successfulComment]);
    vi.spyOn(
      service as unknown as {
        getAuthCredentialsStatus: () => Promise<unknown>;
      },
      "getAuthCredentialsStatus",
    ).mockResolvedValue({
      kind: "ready",
      auth: { client: { getResourceComments } },
    });

    await expect(
      service.getResourceCommentsForTargets(
        [
          { scope: "task_artifact", itemId: "artifact-1" },
          { scope: "task_artifact", itemId: "artifact-2" },
        ],
        "task-1",
      ),
    ).resolves.toEqual([successfulComment]);
  });
});
