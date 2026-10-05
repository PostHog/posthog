import { readFileSync } from "node:fs";
import type { PostHogAPIClient } from "@posthog/api-client/posthog-client";
import type { Task } from "@posthog/shared";
import { describe, expect, it, vi } from "vitest";
import { PiChats } from "./chats";

const task = (runStatus: string, sandboxAlive = true): Task =>
  ({
    id: "t1",
    runtime: "pi",
    latest_run: {
      id: "r1",
      status: runStatus,
      environment: "cloud",
      state: { sandbox_alive: sandboxAlive },
    },
  }) as unknown as Task;

function setup() {
  const api = {
    createTask: vi.fn(async () => ({ id: "t1" })),
    createTaskRun: vi.fn(async () => ({ id: "r1" })),
    startTaskRun: vi.fn(async () => task("queued")),
    runTaskInCloud: vi.fn(async () => ({
      ...task("queued"),
      latest_run: { id: "r2" },
    })),
  };
  const sendMessage = vi.fn(async () => {});
  const uploads = {
    toTask: vi.fn(async (_taskId: string, _filePaths: string[]) => [
      "staged-1",
    ]),
    toRun: vi.fn(
      async (_taskId: string, _runId: string, _filePaths: string[]) => [
        "run-1",
      ],
    ),
  };
  const chats = new PiChats(
    api as unknown as PostHogAPIClient,
    sendMessage,
    "posthog/posthog",
    uploads,
  );
  return { api, sendMessage, uploads, chats };
}

describe("PiChats", () => {
  it("starts a new chat as a pi cloud run carrying the first message", async () => {
    const { api, chats } = setup();

    const started = await chats.start("Fix the flaky test");

    expect(api.createTask).toHaveBeenCalledWith({
      description: "Fix the flaky test",
      repository: "posthog/posthog",
      runtime: "pi",
    });
    expect(api.createTaskRun).toHaveBeenCalledWith("t1", {
      environment: "cloud",
      mode: "interactive",
      piRuntime: true,
    });
    expect(api.startTaskRun).toHaveBeenCalledWith("t1", "r1", {
      pendingUserMessage: "Fix the flaky test",
    });
    expect(started.latest_run?.status).toBe("queued");
  });

  it("starts a local chat as a pi task with no run", async () => {
    const { api, chats } = setup();

    await chats.createLocal("Fix the flaky test");

    expect(api.createTask).toHaveBeenCalledWith({
      description: "Fix the flaky test",
      repository: "posthog/posthog",
      runtime: "pi",
    });
    expect(api.createTaskRun).not.toHaveBeenCalled();
  });

  it("sends a reply straight into a run that is still going", async () => {
    const { api, sendMessage, chats } = setup();

    await chats.reply(task("in_progress"), "Also update the docs");

    expect(sendMessage).toHaveBeenCalledWith(
      "t1",
      "r1",
      "Also update the docs",
      [],
    );
    expect(api.runTaskInCloud).not.toHaveBeenCalled();
  });

  it.each([
    ["has finished", task("completed")],
    ["has lost its sandbox", task("in_progress", false)],
  ])("resumes a run that %s with the reply", async (_, subject) => {
    const { api, sendMessage, chats } = setup();

    const resumed = await chats.reply(subject, "Keep going");

    expect(api.runTaskInCloud).toHaveBeenCalledWith("t1", null, {
      piRuntime: true,
      resumeFromRunId: "r1",
      pendingUserMessage: "Keep going",
    });
    expect(sendMessage).not.toHaveBeenCalled();
    expect(resumed.latest_run?.id).toBe("r2");
  });

  it("resumes the run when a reply finds it already ended", async () => {
    const { api, sendMessage, chats } = setup();
    sendMessage.mockRejectedValueOnce(
      new Error("Failed to queue user message for task run"),
    );

    const resumed = await chats.reply(task("in_progress"), "Keep going");

    expect(api.runTaskInCloud).toHaveBeenCalledWith("t1", null, {
      piRuntime: true,
      resumeFromRunId: "r1",
      pendingUserMessage: "Keep going",
    });
    expect(resumed.latest_run?.id).toBe("r2");
  });

  describe("with images", () => {
    const image = {
      data: Buffer.from("png").toString("base64"),
      mimeType: "image/png",
    };
    const uploaded = (call: unknown[] | undefined) =>
      (call?.at(-1) as string[]).map((path) => readFileSync(path, "utf8"));

    it("uploads them to the task and starts the run carrying them", async () => {
      const { api, uploads, chats } = setup();

      await chats.start("look", [image]);

      expect(uploads.toTask.mock.calls[0]?.[0]).toBe("t1");
      expect(uploaded(uploads.toTask.mock.calls[0])).toEqual(["png"]);
      expect(api.startTaskRun).toHaveBeenCalledWith("t1", "r1", {
        pendingUserMessage: "look",
        pendingUserArtifactIds: ["staged-1"],
      });
    });

    it("uploads them to a live run and sends their ids with the reply", async () => {
      const { sendMessage, uploads, chats } = setup();

      await chats.reply(task("in_progress"), "and this", [image]);

      expect(uploads.toRun.mock.calls[0]?.slice(0, 2)).toEqual(["t1", "r1"]);
      expect(sendMessage).toHaveBeenCalledWith("t1", "r1", "and this", [
        "run-1",
      ]);
    });

    it("uploads them to the task when the reply resumes a finished run", async () => {
      const { api, uploads, chats } = setup();

      await chats.reply(task("completed"), "again", [image]);

      expect(uploads.toRun).not.toHaveBeenCalled();
      expect(api.runTaskInCloud).toHaveBeenCalledWith("t1", null, {
        piRuntime: true,
        resumeFromRunId: "r1",
        pendingUserMessage: "again",
        pendingUserArtifactIds: ["staged-1"],
      });
    });
  });

  it("refuses to continue a chat that was not started with pi", async () => {
    const { chats } = setup();
    const claude = { ...task("completed"), runtime: "acp" } as Task;

    await expect(chats.reply(claude, "hi")).rejects.toThrow(
      "Only pi chats can be continued here",
    );
  });

  it("falls back to the created run when the start response carries none", async () => {
    const { api, chats } = setup();
    api.startTaskRun.mockResolvedValueOnce({ id: "t1" } as Task);

    expect((await chats.start("hi")).latest_run?.id).toBe("r1");
  });
});
