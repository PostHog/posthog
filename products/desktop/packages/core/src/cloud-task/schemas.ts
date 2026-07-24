import type { TaskRunStatus } from "@posthog/shared";
import { z } from "zod";
import type { CloudTaskUpdatePayload } from "./cloud-task-types";

export type { CloudTaskUpdatePayload, TaskRunStatus };

export const TERMINAL_STATUSES = ["completed", "failed", "cancelled"] as const;

export function isTerminalStatus(
  status: TaskRunStatus | string | null | undefined,
): boolean {
  return (
    status !== null &&
    status !== undefined &&
    TERMINAL_STATUSES.includes(status as (typeof TERMINAL_STATUSES)[number])
  );
}

// --- Events ---

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
