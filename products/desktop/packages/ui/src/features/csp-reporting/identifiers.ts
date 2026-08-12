/**
 * postMessage method the sandboxed frame uses to hand a CSP violation to the
 * host. Namespaced under `posthog/` so it never collides with the MCP Apps
 * `ui/notifications/*` methods the same channel carries.
 */
export const CSP_VIOLATION_NOTIFICATION = "posthog/notifications/csp-violation";
