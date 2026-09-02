/**
 * Renderer process DI tokens.
 *
 * IMPORTANT: These tokens are for renderer process only.
 * Never import this file from main code.
 */

// Infrastructure
export const TRPC_CLIENT = Symbol.for("posthog.host.renderer.trpc-client");

// Services
export const TASK_SERVICE = Symbol.for("posthog.host.renderer.task-service");
