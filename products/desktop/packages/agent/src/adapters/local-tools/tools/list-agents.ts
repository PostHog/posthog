import type { TaskRunPeer } from "../../../posthog-api";
import { createSandboxPosthogClient } from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";

export const listAgentsTool = defineLocalTool({
  name: "list_agents",
  description:
    "List the user's other active agent sessions (cloud task runs) that you can message with send_agent_message. " +
    "Reach for this when your work changes something another run may build on (a schema, an API, a shared file), " +
    "or when another active run is better placed to answer a question about its own task. " +
    "Each entry includes the agent_run_id to address, the task it works on, and a `sendable` flag — " +
    "only sendable runs accept messages right now; a queued run appears here but cannot receive yet.",
  schema: {},
  alwaysLoad: true,
  // Deliberately not gated on background/channelMode: peer messaging must work
  // across run modes (an interactive run and a self-driving run can talk).
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" &&
    !!ctx.taskId &&
    !!ctx.taskRunId &&
    meta?.peerMessaging === true,
  handler: async (ctx, _args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Agent discovery is not available in this session.");
    }
    const client = createSandboxPosthogClient();
    if (!client) {
      return errorResult(
        "PostHog API access is not configured in this sandbox.",
      );
    }

    // Fetch AND format inside one guard: the API layer casts the response
    // without runtime validation, so a malformed payload must degrade to the
    // same clean error as a failed request instead of throwing out of the
    // handler.
    try {
      const peers = await client.listTaskRunPeers(ctx.taskId, ctx.taskRunId);
      if (!Array.isArray(peers)) {
        return errorResult(
          "Listing agents failed: unexpected response from PostHog.",
        );
      }
      if (peers.length === 0) {
        return {
          content: [
            {
              type: "text",
              text:
                "No other active agent runs right now. Only the same user's cloud agent runs " +
                "that are currently queued or in progress are listed.",
            },
          ],
        };
      }
      const lines = peers.map(formatPeer);
      return {
        content: [
          {
            type: "text",
            text:
              `Active agent runs you can message (${peers.length}):\n${lines.join("\n")}\n\n` +
              "Use send_agent_message with an agent_run_id marked sendable to message one.",
          },
        ],
      };
    } catch (error) {
      return errorResult(
        `Listing agents failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  },
});

function formatPeer(peer: TaskRunPeer): string {
  const details = [
    `status=${peer.status}`,
    peer.sendable ? "sendable" : "not yet sendable",
    peer.model ? `model=${peer.model}` : null,
    peer.repository ? `repo=${peer.repository}` : null,
    peer.stage ? `stage=${peer.stage}` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(", ");
  return `- agent_run_id=${peer.run_id} — "${peer.task_title}" (${details})`;
}

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}
