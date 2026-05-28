/**
 * Single import surface for fixture data — stories and the console's
 * `mockApi` pull everything from `@posthog/agent-chat/fixtures`.
 *
 * Adding a fixture? Add it to its topical file (`agents.ts`, `sessions.ts`)
 * and re-export here.
 */

export * from './agents'
export * from './bundles'
export * from './scripts'
export * from './sessions'
