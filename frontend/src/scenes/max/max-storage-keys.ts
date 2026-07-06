// Dependency-free constants shared between maxLogic and maxThreadLogic. Keeping these
// out of maxThreadLogic.tsx lets the always-eager maxLogic reference them without pulling
// the heavy Max thread runtime (and the sandbox stream logic) into the authenticated-shell
// eager import graph — see frontend/bin/check-eager-graph.mjs.

/** Key for persisting pending AI prompts across page reloads (e.g., OAuth redirects) */
export const PENDING_AI_PROMPT_KEY = 'posthog_ai_pending_prompt'

/** Which PostHog AI implementation the Max scene renders when the sandbox flag is on (see maxGlobalLogic). */
export const PHAI_VIEW_MODE_KEY = 'posthog_ai_view_mode'
