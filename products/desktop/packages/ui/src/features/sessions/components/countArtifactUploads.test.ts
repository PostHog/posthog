import type { AcpMessage } from "@posthog/shared";
import { describe, expect, it } from "vitest";
import {
  countCompletedArtifactUploads,
  createArtifactUploadTracker,
} from "./countArtifactUploads";

function toolCallEvent(
  sessionUpdate: "tool_call" | "tool_call_update",
  update: { toolCallId: string; status?: string; toolName?: string },
): AcpMessage {
  return {
    type: "acp_message",
    ts: 0,
    message: {
      jsonrpc: "2.0",
      method: "session/update",
      params: {
        update: {
          sessionUpdate,
          toolCallId: update.toolCallId,
          ...(update.status ? { status: update.status } : {}),
          ...(update.toolName
            ? { _meta: { posthog: { toolName: update.toolName } } }
            : {}),
        },
      },
    },
  } as unknown as AcpMessage;
}

const UPLOAD = "mcp__posthog-code-tools__upload_artifact";

describe("createArtifactUploadTracker", () => {
  it("counts an upload once it completes", () => {
    const tracker = createArtifactUploadTracker();
    const events = [
      toolCallEvent("tool_call", { toolCallId: "c1", toolName: UPLOAD }),
    ];

    expect(tracker.update(events)).toBe(0);

    events.push(
      toolCallEvent("tool_call_update", {
        toolCallId: "c1",
        status: "completed",
      }),
    );

    expect(tracker.update(events)).toBe(1);
  });

  it.each([
    ["a repeated completion for one call", "completed", UPLOAD, 1],
    ["a failed upload", "failed", UPLOAD, 0],
    ["another tool completing", "completed", "mcp__other__write_file", 0],
  ])("ignores %s", (_case, status, toolName, expected) => {
    const tracker = createArtifactUploadTracker();
    const events = [
      toolCallEvent("tool_call", { toolCallId: "c1", toolName }),
      toolCallEvent("tool_call_update", { toolCallId: "c1", status }),
      toolCallEvent("tool_call_update", { toolCallId: "c1", status }),
    ];

    expect(tracker.update(events)).toBe(expected);
  });

  it("counts each upload separately", () => {
    const events = [
      toolCallEvent("tool_call", { toolCallId: "c1", toolName: UPLOAD }),
      toolCallEvent("tool_call_update", {
        toolCallId: "c1",
        status: "completed",
      }),
      toolCallEvent("tool_call", { toolCallId: "c2", toolName: UPLOAD }),
      toolCallEvent("tool_call_update", {
        toolCallId: "c2",
        status: "completed",
      }),
    ];

    expect(createArtifactUploadTracker().update(events)).toBe(2);
    expect(countCompletedArtifactUploads(events)).toBe(2);
  });
});
