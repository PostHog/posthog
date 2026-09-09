import { z } from "zod";
import { isNotification, POSTHOG_NOTIFICATIONS } from "./acpNotifications";

const startupEventSchema = z.object({
  message: z.object({
    method: z.string(),
    params: z.object({
      status: z.enum(["sdk_initialization", "setup_hooks"]),
    }),
  }),
});

export type SessionStartupPhase = z.infer<
  typeof startupEventSchema
>["message"]["params"]["status"];

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
