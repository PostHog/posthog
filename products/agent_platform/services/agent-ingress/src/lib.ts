/**
 * Public surface of @posthog/agent-ingress. Internal organization lives
 * under `src/<concern>/`:
 *   - routing/    — Express app builder + slug/host resolver
 *   - enqueue/    — auth + the enqueue helper that all triggers funnel into
 *   - triggers/   — chat, slack, webhook, mcp ingress routes
 *
 * Re-exports everything from `@posthog/agent-shared` too, since most
 * consumers of ingress also need the bus / queue / spec types.
 */

export * from '@posthog/agent-shared'
export * from './enqueue/auth'
export * from './enqueue/enqueue'
export * from './enqueue/verifiers'
export * from './routing/resolver'
export * from './routing/server'
export * from './triggers/chat'
export * from './triggers/mcp'
export * from './triggers/slack'
export * from './triggers/webhook'
