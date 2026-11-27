/** Key for persisting pending AI prompts across page reloads (e.g., OAuth redirects) */
export const PENDING_AI_PROMPT_KEY = 'posthog_ai_pending_prompt'

/** Classic PostHog AI prefills its composer with this prompt the next time it mounts. */
export function stashPendingAiPrompt(prompt: string): void {
    try {
        sessionStorage.setItem(PENDING_AI_PROMPT_KEY, JSON.stringify({ prompt, timestamp: Date.now() }))
    } catch {
        // sessionStorage might be unavailable
    }
}
