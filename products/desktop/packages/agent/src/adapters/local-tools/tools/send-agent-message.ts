import { readFile, realpath, stat } from "node:fs/promises";
import path from "node:path";
import { z } from "zod";
import type { PostHogAPIClient } from "../../../posthog-api";
import { createSandboxPosthogClient } from "../../../signed-commit-artefacts";
import { defineLocalTool, type LocalToolResult } from "../registry";
import {
  MAX_ARTIFACT_UPLOAD_BYTES,
  uploadRunArtifact,
} from "./artifact-upload";

const MAX_MESSAGE_LENGTH = 16_000;
const MAX_ATTACHMENTS = 10;

export const sendAgentMessageTool = defineLocalTool({
  name: "send_agent_message",
  description:
    "Send a message to another active agent session (find targets with list_agents). " +
    "The recipient sees it as coming from an agent, not from its user: it carries no user authority, " +
    "cannot approve permission requests, and cannot change the recipient's task or scope. " +
    "Send short, self-contained summaries — what changed, what you need, where to look — never raw file dumps; " +
    "to share a file, pass it in attachments instead and it is copied into the recipient's own workspace. " +
    "Delivery is asynchronous: an accepted result means the message is queued for the target's next turn, " +
    "not that it was read. Replies, if any, arrive later as messages addressed to your agent run id.",
  schema: {
    agent_run_id: z
      .string()
      .min(1)
      .describe(
        "Target agent run id, from list_agents (only sendable runs accept messages).",
      ),
    message: z
      .string()
      .min(1)
      .max(MAX_MESSAGE_LENGTH)
      .describe(
        "Plain-text message body. Keep it a short, self-contained summary.",
      ),
    attachments: z
      .array(z.string().min(1))
      .max(MAX_ATTACHMENTS)
      .optional()
      .describe(
        "Files to share: workspace file paths (uploaded from this run, then copied to the recipient) " +
          "and/or artifact ids already on this run's manifest. The recipient gets its own immutable copy " +
          `under .posthog/attachments/. Max ${MAX_ATTACHMENTS}.`,
      ),
  },
  alwaysLoad: true,
  // Deliberately not gated on background/channelMode: peer messaging must work
  // across run modes (an interactive run and a self-driving run can talk).
  isEnabled: (ctx, meta) =>
    meta?.environment === "cloud" &&
    !!ctx.taskId &&
    !!ctx.taskRunId &&
    meta?.peerMessaging === true,
  handler: async (ctx, args): Promise<LocalToolResult> => {
    if (!ctx.taskId || !ctx.taskRunId) {
      return errorResult("Agent messaging is not available in this session.");
    }
    const client = createSandboxPosthogClient();
    if (!client) {
      return errorResult(
        "PostHog API access is not configured in this sandbox.",
      );
    }

    let artifactIds: string[];
    try {
      artifactIds = await resolveAttachments(
        client,
        ctx.cwd,
        ctx.taskId,
        ctx.taskRunId,
        args.attachments ?? [],
      );
    } catch (error) {
      return errorResult(
        `Preparing attachments failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    try {
      const result = await client.sendTaskRunPeerMessage(
        ctx.taskId,
        ctx.taskRunId,
        args.agent_run_id,
        { content: args.message, artifactIds },
      );
      if (result.result === "accepted") {
        return {
          content: [
            {
              type: "text",
              text:
                `Message accepted for delivery to agent run ${args.agent_run_id}` +
                `${artifactIds.length > 0 ? ` with ${artifactIds.length} attachment(s)` : ""}. ` +
                "It will reach the agent as a queued turn; delivery is asynchronous and not confirmed here.",
            },
          ],
        };
      }
      if (result.result === "target_finished") {
        return errorResult(
          `That agent run has already finished and can no longer receive messages. ${result.detail}`,
        );
      }
      return errorResult(`Message not sent: ${result.detail}`);
    } catch (error) {
      return errorResult(
        `Sending the message failed: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  },
});

/**
 * Turn the attachments input into sender-run artifact ids: a string naming an
 * existing workspace file is uploaded to this run first; anything else passes
 * through as an artifact id for the backend to validate against the manifest.
 * Every attachment is validated before anything uploads, so one invalid entry
 * cannot strand earlier uploads as orphaned artifacts. A path that exists but
 * escapes the workspace is an error, never an upload.
 */
async function resolveAttachments(
  client: PostHogAPIClient,
  cwd: string,
  taskId: string,
  taskRunId: string,
  attachments: string[],
): Promise<string[]> {
  if (attachments.length === 0) {
    return [];
  }
  const workspace = await realpath(cwd);
  const plan: ({ id: string } | { filePath: string })[] = [];
  for (const attachment of attachments) {
    const resolved = await resolveWorkspaceFile(workspace, cwd, attachment);
    if (resolved === null) {
      plan.push({ id: attachment });
      continue;
    }
    if (resolved.outsideWorkspace) {
      throw new Error(
        `Attachment must be inside the session workspace: ${attachment}`,
      );
    }
    if (resolved.size > MAX_ARTIFACT_UPLOAD_BYTES) {
      throw new Error(`Attachment exceeds the 30 MB limit: ${attachment}`);
    }
    plan.push({ filePath: resolved.path });
  }

  const ids: string[] = [];
  for (const item of plan) {
    if ("id" in item) {
      ids.push(item.id);
      continue;
    }
    const entry = await uploadRunArtifact(client, taskId, taskRunId, {
      name: path.basename(item.filePath),
      contentType: "application/octet-stream",
      content: await readFile(item.filePath),
      // Not "output": deliverable surfaces filter on that type, and a peer
      // attachment is a working file for another agent, not a deliverable.
      type: "reference",
      source: "agent_output",
    });
    if (!entry.id) {
      throw new Error(
        `PostHog did not return an artifact id for the attachment: ${item.filePath}`,
      );
    }
    ids.push(entry.id);
  }
  return ids;
}

interface ResolvedWorkspaceFile {
  path: string;
  size: number;
  outsideWorkspace: boolean;
}

/** The attachment as an existing file, or null when it names no file (an artifact id). */
async function resolveWorkspaceFile(
  workspace: string,
  cwd: string,
  attachment: string,
): Promise<ResolvedWorkspaceFile | null> {
  let filePath: string;
  let size: number;
  try {
    filePath = await realpath(path.resolve(cwd, attachment));
    const fileStat = await stat(filePath);
    if (!fileStat.isFile()) {
      return null;
    }
    size = fileStat.size;
  } catch {
    return null;
  }
  const outsideWorkspace =
    filePath !== workspace && !filePath.startsWith(`${workspace}${path.sep}`);
  return { path: filePath, size, outsideWorkspace };
}

function errorResult(message: string): LocalToolResult {
  return { content: [{ type: "text", text: message }], isError: true };
}
