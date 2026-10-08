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

function setup({ canReopen = false } = {}) {
  const api = {
    createTask: vi.fn(async () => ({ id: "t1" })),
    createTaskRun: vi.fn(async () => ({ id: "r1" })),
    startTaskRun: vi.fn(async () => task("queued")),
    runTaskInCloud: vi.fn(async () => ({
      ...task("queued"),
      latest_run: { id: "r2" },
    })),
    resumeRunInCloud: vi.fn(async () => ({ id: "r1", status: "queued" })),
    getIntegrations: vi.fn(async () => [
      { id: 7, kind: "github" },
      { id: 8, kind: "slack" },
    ]),
    getGithubUserIntegrations: vi.fn(async () => [
      { id: "mine", installation_id: "i-1" },
    ]),
    getGithubRepositoriesPage: vi.fn(async () => ({
      repositories: ["posthog/posthog"],
      hasMore: false,
      total: 1,
    })),
    getGithubUserRepositoriesPage: vi.fn(async () => ({
      repositories: ["me/side-project"],
      hasMore: false,
      total: 1,
    })),
  };
  const sendMessage = vi.fn(async () => {});
  const agentRestarted = vi.fn(
    async (_taskId: string, _runId: string, _since: number) => {},
  );
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
    canReopen ? agentRestarted : undefined,
  );
  return { api, sendMessage, uploads, chats, agentRestarted };
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

  it.each([
    [
      "several repositories and the team's GitHub integration",
      ["posthog/posthog-js", "posthog/posthog"],
      {
        repository: "posthog/posthog-js",
        repositories: ["posthog/posthog-js", "posthog/posthog"],
        github_integration: 7,
      },
    ],
    [
      "the personal GitHub connection a searched repository came from",
      ["me/side-project", "posthog/posthog"],
      {
        repository: "me/side-project",
        repositories: ["me/side-project", "posthog/posthog"],
        github_user_integration: "mine",
      },
    ],
    ["no repository when none was picked", [], { repository: undefined }],
  ])("starts a cloud chat with %s", async (_, repositories, expected) => {
    const { api, chats } = setup();
    await chats.searchRepositories("");

    await chats.start("Look into it", [], repositories);

    expect(api.createTask).toHaveBeenCalledWith({
      description: "Look into it",
      runtime: "pi",
      ...expected,
    });
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

  it("starts a new run that continues a finished one, when it cannot bring the run back", async () => {
    const { api, sendMessage, chats } = setup();

    const resumed = await chats.reply(task("completed"), "Keep going");

    expect(api.runTaskInCloud).toHaveBeenCalledWith("t1", null, {
      piRuntime: true,
      resumeFromRunId: "r1",
      pendingUserMessage: "Keep going",
    });
    expect(sendMessage).not.toHaveBeenCalled();
    expect(resumed.latest_run?.id).toBe("r2");
  });

  describe("bringing a stopped run back", () => {
    it.each([
      ["has finished", task("completed"), 0],
      ["has lost its sandbox", task("in_progress", false), 1],
    ])(
      "brings back a run that %s on the same run, then sends the reply to its agent",
      async (_, subject, failedSends) => {
        const { api, sendMessage, chats, agentRestarted } = setup({
          canReopen: true,
        });
        for (let i = 0; i < failedSends; i++)
          sendMessage.mockRejectedValueOnce(new Error("No active sandbox"));
        const onReopen = vi.fn();

        const replied = await chats.reply(subject, "Keep going", [], onReopen);

        expect(onReopen).toHaveBeenLastCalledWith(
          expect.objectContaining({
            latest_run: expect.objectContaining({ id: "r1", status: "queued" }),
          }),
        );
        expect(api.resumeRunInCloud).toHaveBeenCalledWith("t1", "r1");
        expect(agentRestarted).toHaveBeenCalledWith(
          "t1",
          "r1",
          expect.any(Number),
        );
        expect(sendMessage).toHaveBeenLastCalledWith(
          "t1",
          "r1",
          "Keep going",
          [],
        );
        expect(agentRestarted.mock.invocationCallOrder[0]).toBeLessThan(
          sendMessage.mock.invocationCallOrder.at(-1) ?? 0,
        );
        expect(api.runTaskInCloud).not.toHaveBeenCalled();
        expect(replied.latest_run).toMatchObject({
          id: "r1",
          status: "queued",
        });
      },
    );

    it("starts a new run that continues it when the server still counts it as running", async () => {
      const { api, chats } = setup({ canReopen: true });
      api.resumeRunInCloud.mockRejectedValueOnce(
        new Error("Run is already active in cloud"),
      );

      const replied = await chats.reply(task("completed"), "Keep going");

      expect(api.runTaskInCloud).toHaveBeenCalledWith("t1", null, {
        piRuntime: true,
        resumeFromRunId: "r1",
        pendingUserMessage: "Keep going",
      });
      expect(replied.latest_run?.id).toBe("r2");
    });

    it("keeps the reply unsent when the agent does not come back", async () => {
      const { sendMessage, chats, agentRestarted } = setup({ canReopen: true });
      agentRestarted.mockRejectedValueOnce(
        new Error("The sandbox took too long to come back"),
      );

      await expect(
        chats.reply(task("completed"), "Keep going"),
      ).rejects.toThrow("took too long");
      expect(sendMessage).not.toHaveBeenCalled();
    });
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

  describe("on the user's Claude plan", () => {
    const claude = (runStatus: string): Task =>
      ({ ...task(runStatus), runtime: "acp" }) as Task;

    it("starts a new chat as a Claude Code cloud run that asks for the plan token", async () => {
      const { api, chats } = setup();

      await chats.start("Fix the flaky test", [], undefined, "claude");

      expect(api.createTask).toHaveBeenCalledWith({
        description: "Fix the flaky test",
        repository: "posthog/posthog",
        runtime: "acp",
        runtime_adapter: "claude",
      });
      expect(api.createTaskRun).toHaveBeenCalledWith("t1", {
        environment: "cloud",
        mode: "interactive",
        adapter: "claude",
        claudeModelAccess: "own-subscription",
      });
    });

    it("sends a reply into a Claude run that is still going", async () => {
      const { sendMessage, chats } = setup();

      await chats.reply(claude("in_progress"), "Also update the docs");

      expect(sendMessage).toHaveBeenCalledWith(
        "t1",
        "r1",
        "Also update the docs",
        [],
      );
    });

    it("continues a finished Claude run with a new run on the same plan", async () => {
      const { api, chats } = setup();

      await chats.reply(claude("completed"), "Keep going");

      expect(api.runTaskInCloud).toHaveBeenCalledWith("t1", null, {
        adapter: "claude",
        claudeModelAccess: "own-subscription",
        resumeFromRunId: "r1",
        pendingUserMessage: "Keep going",
      });
    });
  });

  it("refuses to continue a chat from another harness", async () => {
    const { chats } = setup();
    const codex = {
      ...task("completed"),
      runtime: "acp",
      latest_run: { ...task("completed").latest_run, runtime_adapter: "codex" },
    } as unknown as Task;

    await expect(chats.reply(codex, "hi")).rejects.toThrow(
      "Only pi and Claude chats can be continued here",
    );
  });

  it("falls back to the created run when the start response carries none", async () => {
    const { api, chats } = setup();
    api.startTaskRun.mockResolvedValueOnce({ id: "t1" } as Task);

    expect((await chats.start("hi")).latest_run?.id).toBe("r1");
  });
});
