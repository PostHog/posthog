import { z } from "zod";

/** The Claude SDK payload sent when a background task settles. */
export const taskNotificationParamsSchema = z
  .object({
    sessionId: z.string().optional(),
    taskId: z.string(),
    status: z.enum(["completed", "failed", "stopped"]),
    summary: z.string(),
    outputFile: z.string().optional(),
    payload: z.record(z.string(), z.unknown()).optional(),
  })
  .passthrough();

export type TaskNotificationParams = z.infer<
  typeof taskNotificationParamsSchema
>;

export function parseTaskNotificationParams(
  value: unknown,
): TaskNotificationParams | null {
  const result = taskNotificationParamsSchema.safeParse(value);
  if (!result.success) return null;

  return {
    ...result.data,
    // Older logs have no nested raw payload. Their params are the complete data
    // available for that notification, so keep those params inspectable.
    payload:
      result.data.payload ??
      (typeof value === "object" && value !== null
        ? (value as Record<string, unknown>)
        : undefined),
  };
}
