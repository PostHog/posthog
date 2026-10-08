import { beforeEach, describe, expect, it, vi } from "vitest";
import { createBackgroundJobsExtension } from "./extension";
import { __resetBackgroundJobsForTesting, startBackgroundJob } from "./jobs";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;

interface RegisteredTool {
  name: string;
  execute: (
    toolCallId: string,
    params: Record<string, unknown>,
  ) => Promise<{ content: Array<{ type: string; text?: string }> }>;
}

function fakePi() {
  const handlers = new Map<string, Handler[]>();
  const tools = new Map<string, RegisteredTool>();
  const renderers = new Map<string, unknown>();
  const sentMessages: unknown[] = [];
  const pi = {
    on: (event: string, handler: Handler) => {
      handlers.set(event, [...(handlers.get(event) ?? []), handler]);
    },
    registerTool: (tool: unknown) => {
      const t = tool as RegisteredTool;
      tools.set(t.name, t);
    },
    registerMessageRenderer: (customType: string, renderer: unknown) => {
      renderers.set(customType, renderer);
    },
    sendMessage: (message: unknown) => {
      sentMessages.push(message);
    },
  };
  return {
    pi,
    tools,
    renderers,
    sentMessages,
    emit: async (event: string, payload: unknown) => {
      for (const handler of handlers.get(event) ?? [])
        await handler(payload, undefined);
    },
  };
}

describe("createBackgroundJobsExtension", () => {
  beforeEach(() => {
    __resetBackgroundJobsForTesting();
  });

  it("registers a message renderer for background-job messages", () => {
    const { pi, renderers } = fakePi();
    createBackgroundJobsExtension()(pi as never);
    expect(renderers.has("background-job")).toBe(true);
  });

  it("list_background_jobs reports no jobs when none are running", async () => {
    const { pi, tools } = fakePi();
    createBackgroundJobsExtension()(pi as never);
    const result = await tools.get("list_background_jobs")?.execute("id", {});
    expect(result?.content[0]?.text).toBe("No background jobs running.");
  });

  it("list_background_jobs reports running jobs by label", async () => {
    const { pi, tools } = fakePi();
    startBackgroundJob({
      pi,
      label: "long task",
      work: () => new Promise(() => {}),
      onSuccess: () => "",
    });
    createBackgroundJobsExtension()(pi as never);
    const result = await tools.get("list_background_jobs")?.execute("id", {});
    expect(result?.content[0]?.text).toContain("long task");
  });

  it("cancel_background_job cancels a known job and reports unknown ids", async () => {
    const { pi, tools } = fakePi();
    const start = startBackgroundJob({
      pi,
      label: "cancel me",
      work: (signal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new Error("aborted")));
        }),
      onSuccess: () => "",
    });
    createBackgroundJobsExtension()(pi as never);

    const ok = await tools
      .get("cancel_background_job")
      ?.execute("id", { jobId: start.jobId });
    expect(ok?.content[0]?.text).toContain("Cancelling job");

    const missing = await tools
      .get("cancel_background_job")
      ?.execute("id", { jobId: "nope" });
    expect(missing?.content[0]?.text).toContain("No running job");
  });

  it("aborts every running job on session_shutdown", async () => {
    const { pi, emit, sentMessages } = fakePi();
    createBackgroundJobsExtension()(pi as never);
    startBackgroundJob({
      pi,
      label: "orphan",
      work: (signal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new Error("aborted")));
        }),
      onSuccess: () => "",
    });

    await emit("session_shutdown", {});
    await vi.waitFor(() => expect(sentMessages).toHaveLength(1));
  });
});
