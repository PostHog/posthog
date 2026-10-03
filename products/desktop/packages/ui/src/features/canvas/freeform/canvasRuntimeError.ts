import type { CanvasRuntimeErrorProperties } from "@posthog/shared/analytics-events";

export function canvasRuntimeErrorAnalytics(
  message: string,
): Pick<CanvasRuntimeErrorProperties, "error_type" | "csp_directive"> {
  const errorType =
    message.match(/^([A-Z][A-Za-z0-9]*(?:Error|Exception))\b/)?.[1] ??
    "unknown";
  const cspDirective = message.match(
    /^SecurityPolicyViolationError: ([a-z][a-z-]{0,63})$/,
  )?.[1];
  return {
    error_type: errorType,
    ...(cspDirective ? { csp_directive: cspDirective } : {}),
  };
}
