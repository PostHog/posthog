import type { AgentSessionErrorProperties } from "@posthog/shared/analytics-events";
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

const STARTUP_STEPS = [
  "initialization",
  "resumption",
  "fork",
  "setup hooks",
  "model switch",
  "effort update",
  "fast mode update",
];

const STARTUP_ERROR_PATTERN =
  /^Session (.+?) (timed out after \d+ms|failed(?::|$))/;

export function classifySessionStartError(
  message: string,
): Pick<AgentSessionErrorProperties, "failure_reason" | "startup_step"> {
  const match = STARTUP_ERROR_PATTERN.exec(message);
  if (!match || !STARTUP_STEPS.includes(match[1])) {
    return { failure_reason: "other" };
  }
  return {
    failure_reason: match[2].startsWith("failed")
      ? "startup_failed"
      : "startup_timeout",
    startup_step: match[1],
  };
}

const MAX_TRACKED_ERROR_MESSAGE_LENGTH = 500;

export function describeSessionStartError(
  message: string,
  requestedModel: string | undefined,
): Pick<
  AgentSessionErrorProperties,
  "failure_reason" | "startup_step" | "requested_model" | "error_message"
> {
  return {
    ...classifySessionStartError(message),
    error_message: message.slice(0, MAX_TRACKED_ERROR_MESSAGE_LENGTH),
    ...(requestedModel ? { requested_model: requestedModel } : {}),
  };
}

export function isModelSwitchStartupError(
  message: string | undefined,
): boolean {
  return (
    message !== undefined &&
    classifySessionStartError(message).startup_step === "model switch"
  );
}
