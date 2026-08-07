import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { describe, expect, it, vi } from "vitest";
import { SessionService } from "./sessionService";

describe("SessionService task comments", () => {
  it("loads all comments through the authenticated client", async () => {
    const service = Object.create(SessionService.prototype) as SessionService;
    const comments = [{ id: "comment-1" }] as ResourceComment[];
    const getTaskComments = vi.fn().mockResolvedValue(comments);
    vi.spyOn(
      service as unknown as {
        getAuthCredentialsStatus: () => Promise<unknown>;
      },
      "getAuthCredentialsStatus",
    ).mockResolvedValue({
      kind: "ready",
      auth: { client: { getTaskComments } },
    });

    await expect(service.getTaskComments("task-1")).resolves.toEqual(comments);
    expect(getTaskComments).toHaveBeenCalledWith("task-1");
  });
});
