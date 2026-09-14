import { z } from "zod";
import { isNotification, POSTHOG_NOTIFICATIONS } from "./acpNotifications";

const startupPhaseSchema = z.enum(["sdk_initialization", "setup_hooks"]);

const startupEventSchema = z.object({
  message: z.object({
    method: z.string(),
    params: z.object({ status: startupPhaseSchema }),
  }),
});

export type SessionStartupPhase = z.infer<typeof startupPhaseSchema>;

export function isSessionStartupPhase(
  status: string,
): status is SessionStartupPhase {
  return startupPhaseSchema.safeParse(status).success;
}

export function readSessionStartupPhase(
  event: unknown,
): SessionStartupPhase | undefined {
  const result = startupEventSchema.safeParse(event);
  if (
    result.success &&
    isNotification(result.data.message.method, POSTHOG_NOTIFICATIONS.STATUS)
  ) {
    return result.data.message.params.status;
  }
  return undefined;
}
