import type { CloudTaskUpdatePayload } from "@posthog/shared";
import { z } from "zod";

export {
  type CloudTaskUpdatePayload,
  isTerminalStatus,
  type TaskRunStatus,
  TERMINAL_STATUSES,
} from "@posthog/shared";

export const cloudContextOutput = z
  .object({ apiHost: z.string(), teamId: z.number() })
  .nullable();

// --- Events ---

export const progressNotificationParams = z.object({
  step: z.string().min(1),
  status: z.enum(["in_progress", "completed", "failed"]),
  label: z.string().min(1),
  group: z.string().min(1),
  detail: z.string().optional(),
});

export const CloudTaskEvent = {
  Update: "cloud-task-update",
} as const;

export interface CloudTaskEvents {
  [CloudTaskEvent.Update]: CloudTaskUpdatePayload;
}

// --- tRPC Schemas ---

export const watchInput = z.object({
  taskId: z.string(),
  runId: z.string(),
  apiHost: z.string(),
  teamId: z.number(),
  resumeFromEntryCount: z.number().optional(),
});

export type WatchInput = z.infer<typeof watchInput>;

export const unwatchInput = z.object({
  taskId: z.string(),
  runId: z.string(),
});

export const retryInput = z.object({
  taskId: z.string(),
  runId: z.string(),
});

export const onUpdateInput = z.object({
  taskId: z.string(),
  runId: z.string(),
});

export const sendCommandInput = z.object({
  taskId: z.string(),
  id: z.string().optional(),
  runId: z.string(),
  apiHost: z.string(),
  teamId: z.number(),
  method: z.enum([
    "user_message",
    "cancel",
    "close",
    "permission_response",
    "set_config_option",
    "mcp_response",
    "pi/rpc",
    "queue_get",
    "queue_clear",
    "side_question",
  ]),
  params: z.record(z.string(), z.unknown()).optional(),
});

export type SendCommandInput = z.infer<typeof sendCommandInput>;

export const designateRelayedMcpServersInput = z.object({
  runId: z.string(),
  servers: z.array(z.string().min(1)).max(20),
});

export type DesignateRelayedMcpServersInput = z.infer<
  typeof designateRelayedMcpServersInput
>;

export const sendCommandOutput = z.object({
  success: z.boolean(),
  result: z.unknown().optional(),
  error: z.string().optional(),
  status: z.number().optional(),
  retryable: z.boolean().optional(),
});

export type SendCommandOutput = z.infer<typeof sendCommandOutput>;

export const stopInput = z.object({
  taskId: z.string(),
  runId: z.string(),
  reason: z.string().optional(),
});

export type StopInput = z.infer<typeof stopInput>;

export const stopOutput = z.object({
  success: z.boolean(),
  runStatus: z.string().optional(),
  error: z.string().optional(),
  retryable: z.boolean().optional(),
});

export type StopOutput = z.infer<typeof stopOutput>;
