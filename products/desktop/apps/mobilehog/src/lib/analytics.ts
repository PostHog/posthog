import PostHog from "posthog-react-native";
import type { Session } from "@/lib/auth";

const key = process.env.EXPO_PUBLIC_POSTHOG_API_KEY;
const host = process.env.EXPO_PUBLIC_POSTHOG_HOST;
const allowed = new Set([
  "operation",
  "success",
  "has_images",
  "team",
  "task_id",
  "run_id",
  "$lib",
  "$lib_version",
  "$app_version",
  "$app_build",
  "$app_namespace",
  "$os_name",
  "$os_version",
  "$session_id",
  "$exception_level",
  "$exception_list",
  "$process_person_profile",
  "$is_identified",
  "$anon_distinct_id",
]);

export const posthog =
  key && host
    ? new PostHog(key, {
        host,
        captureAppLifecycleEvents: false,
        disableGeoip: true,
        enableSessionReplay: false,
        personProfiles: "identified_only",
        errorTracking: {
          autocapture: {
            uncaughtExceptions: true,
            unhandledRejections: true,
            console: false,
          },
        },
        before_send: (event) => {
          if (!event) return null;
          event.properties = Object.fromEntries(
            Object.entries(event.properties ?? {}).filter(([name]) =>
              allowed.has(name),
            ),
          );
          // Request errors can contain response bodies. Keep stacks, never exception text.
          const exceptions = event.properties.$exception_list;
          if (Array.isArray(exceptions))
            event.properties.$exception_list = exceptions.flatMap((error) => {
              if (!error || typeof error !== "object" || Array.isArray(error))
                return [];
              const stack = error.stacktrace;
              const frames =
                stack &&
                typeof stack === "object" &&
                !Array.isArray(stack) &&
                Array.isArray(stack.frames)
                  ? stack.frames
                  : [];
              return [
                {
                  type: "Error",
                  value: "Mobile operation failed",
                  stacktrace: {
                    type: "raw",
                    frames: frames.flatMap((frame) => {
                      if (
                        !frame ||
                        typeof frame !== "object" ||
                        Array.isArray(frame)
                      )
                        return [];
                      return [
                        {
                          filename:
                            typeof frame.filename === "string"
                              ? frame.filename.split(/[?#]/)[0]
                              : null,
                          function: frame.function ?? null,
                          lineno: frame.lineno ?? null,
                          colno: frame.colno ?? null,
                          in_app: frame.in_app ?? null,
                          module: frame.module ?? null,
                          platform: frame.platform ?? null,
                          debug_id: frame.debug_id ?? null,
                          map_id: frame.map_id ?? null,
                          instruction_addr: frame.instruction_addr ?? null,
                        },
                      ];
                    }),
                  },
                },
              ];
            });
          return event;
        },
      })
    : null;

export function identifyAnalytics(session: Session | null): void {
  if (!session) {
    posthog?.reset();
    return;
  }
  posthog?.identify(`${session.host}:${session.userId}`, {
    team: session.projectId,
  });
  posthog?.register({ team: session.projectId });
}

export function captureOutcome(
  operation: string,
  success: boolean,
  properties: { has_images?: boolean } = {},
): void {
  posthog?.capture("mobile_task_action", { operation, success, ...properties });
}

export function captureFailure(operation: string, error?: unknown): void {
  const safe = new Error("Mobile operation failed");
  if (error instanceof Error)
    safe.stack = error.stack?.replace(
      /^.*\n/,
      "Error: Mobile operation failed\n",
    );
  posthog?.captureException(safe, { operation });
}

export const engineAnalytics = {
  initialize: () => {},
  track: (event: string) => {
    posthog?.capture("mobile_task_connection", { operation: event });
  },
  identify: () => {},
  setCurrentUserId: () => {},
  getCurrentUserId: () => null,
  getOrCreateSessionId: () => posthog?.getSessionId() ?? "mobilehog",
  resetUser: () => {},
  captureException: (error: unknown) =>
    captureFailure("task_connection", error),
  flush: async () => {
    await posthog?.flush();
  },
  shutdown: async () => {
    await posthog?.flush();
  },
};
