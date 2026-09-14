import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sendTaskRunPeerMessage = vi.fn();
const listTaskRunPeers = vi.fn();
const uploadTaskArtifacts = vi.fn();
const prepareTaskArtifactUploads = vi.fn();
const finalizeTaskArtifactUploads = vi.fn();

vi.mock("../../../signed-commit-artefacts", () => ({
  createSandboxPosthogClient: () => ({
    sendTaskRunPeerMessage,
    listTaskRunPeers,
    uploadTaskArtifacts,
    prepareTaskArtifactUploads,
    finalizeTaskArtifactUploads,
  }),
}));

import { enabledLocalTools } from "../index";
import type { LocalToolCtx, LocalToolGateMeta } from "../registry";
import { sendAgentMessageTool } from "./send-agent-message";

describe("send_agent_message tool", () => {
  let cwd: string;

  beforeEach(async () => {
    vi.clearAllMocks();
    cwd = await mkdtemp(path.join(os.tmpdir(), "send-agent-message-"));
    sendTaskRunPeerMessage.mockResolvedValue({
      result: "accepted",
      detail: "queued",
      message_id: "msg-1",
    });
    // Direct upload fails fast so attachment uploads exercise the inline path,
    // which needs no fetch stub.
    prepareTaskArtifactUploads.mockRejectedValue(new Error("storage offline"));
    uploadTaskArtifacts.mockResolvedValue([
      {
        id: "uploaded-artifact-1",
        name: "notes.md",
        type: "output",
        storage_path: "tasks/artifacts/notes.md",
      },
    ]);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await rm(cwd, { recursive: true, force: true });
  });

  // The `finish` tool's background-based gate silently hid it from every Pi run;
  // these cases pin the peer gate to fields all cloud runs supply plus the
  // explicit capability — and to nothing mode-specific.
  it.each([
    {
      name: "cloud run with peer messaging enabled",
      meta: { environment: "cloud", peerMessaging: true },
      expected: true,
    },
    {
      name: "background channel-mode run (mode-agnostic gate)",
      meta: {
        environment: "cloud",
        peerMessaging: true,
        background: true,
        channelMode: true,
      },
      expected: true,
    },
    {
      name: "cloud run without the capability",
      meta: { environment: "cloud" },
      expected: false,
    },
    {
      name: "local run with the capability",
      meta: { environment: "local", peerMessaging: true },
      expected: false,
    },
    {
      name: "no gate meta",
      meta: undefined,
      expected: false,
    },
  ] as {
    name: string;
    meta: LocalToolGateMeta | undefined;
    expected: boolean;
  }[])("gate: $name → $expected", ({ meta, expected }) => {
    const ctx: LocalToolCtx = {
      cwd: "/repo",
      taskId: "task-1",
      taskRunId: "run-1",
    };
    const names = enabledLocalTools(ctx, meta).map((t) => t.name);
    expect(names.includes("send_agent_message")).toBe(expected);
    expect(names.includes("list_agents")).toBe(expected);
  });

  it("gate requires a task run id", () => {
    const tools = enabledLocalTools(
      { cwd: "/repo", taskId: "task-1" },
      { environment: "cloud", peerMessaging: true },
    );
    expect(tools.some((t) => t.name === "send_agent_message")).toBe(false);
  });

  it("uploads workspace-path attachments and passes artifact ids through", async () => {
    await writeFile(path.join(cwd, "notes.md"), "schema changed");

    const result = await sendAgentMessageTool.handler(
      { cwd, taskId: "task-1", taskRunId: "run-1" },
      {
        agent_run_id: "target-run",
        message: "heads up",
        attachments: ["notes.md", "already-an-artifact-id"],
      },
    );

    expect(result.isError).toBeUndefined();
    expect(uploadTaskArtifacts).toHaveBeenCalledTimes(1);
    // Never "output": that type renders in every user-facing deliverable panel.
    expect(uploadTaskArtifacts).toHaveBeenCalledWith("task-1", "run-1", [
      expect.objectContaining({ type: "reference" }),
    ]);
    expect(sendTaskRunPeerMessage).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "target-run",
      {
        content: "heads up",
        artifactIds: ["uploaded-artifact-1", "already-an-artifact-id"],
      },
    );
  });

  it("uploads nothing when a later attachment fails validation", async () => {
    await writeFile(path.join(cwd, "notes.md"), "ok");
    const outside = await mkdtemp(path.join(os.tmpdir(), "outside-"));
    const secret = path.join(outside, "secret.txt");
    await writeFile(secret, "s");
    try {
      const result = await sendAgentMessageTool.handler(
        { cwd, taskId: "task-1", taskRunId: "run-1" },
        {
          agent_run_id: "target-run",
          message: "hi",
          attachments: ["notes.md", secret],
        },
      );
      expect(result.isError).toBe(true);
      expect(uploadTaskArtifacts).not.toHaveBeenCalled();
      expect(prepareTaskArtifactUploads).not.toHaveBeenCalled();
      expect(sendTaskRunPeerMessage).not.toHaveBeenCalled();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it("refuses an existing file outside the workspace instead of treating it as an id", async () => {
    const outside = await mkdtemp(path.join(os.tmpdir(), "outside-"));
    const secret = path.join(outside, "secret.txt");
    await writeFile(secret, "s");
    try {
      const result = await sendAgentMessageTool.handler(
        { cwd, taskId: "task-1", taskRunId: "run-1" },
        { agent_run_id: "target-run", message: "hi", attachments: [secret] },
      );
      expect(result.isError).toBe(true);
      expect(sendTaskRunPeerMessage).not.toHaveBeenCalled();
    } finally {
      await rm(outside, { recursive: true, force: true });
    }
  });

  it.each([
    {
      result: { result: "rejected", detail: "Rate limit: wait before sending" },
      expectInText: "Rate limit",
    },
    {
      result: { result: "target_finished", detail: "The target run finished." },
      expectInText: "already finished",
    },
  ])(
    "surfaces a non-accepted backend result as an error ($result.result)",
    async ({ result: backendResult, expectInText }) => {
      sendTaskRunPeerMessage.mockResolvedValue(backendResult);

      const result = await sendAgentMessageTool.handler(
        { cwd, taskId: "task-1", taskRunId: "run-1" },
        { agent_run_id: "target-run", message: "hi" },
      );

      expect(result.isError).toBe(true);
      expect(result.content[0]?.text).toContain(expectInText);
    },
  );

  it("reports accepted as queued, not delivered", async () => {
    const result = await sendAgentMessageTool.handler(
      { cwd, taskId: "task-1", taskRunId: "run-1" },
      { agent_run_id: "target-run", message: "hi" },
    );

    expect(result.isError).toBeUndefined();
    expect(result.content[0]?.text).toContain("accepted for delivery");
    expect(result.content[0]?.text).toContain("asynchronous");
  });
});
