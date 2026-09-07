/**
 * Wizard program identifiers. In code these are "workflows", after the wire field the CLI sends
 * (`workflow_id`); "program" is the CLI's user-facing word for the same thing.
 *
 * The CLI sends its program id as `workflow_id` on every session push, so each program is its own
 * session channel. Kept in their own module because both the session detector and the installation
 * progress layer need them, and those two import each other.
 */

/** The SDK install — what the app-wide sync surfaces watch by default. */
export const POSTHOG_INTEGRATION_WORKFLOW_ID = 'posthog-integration'

/** `wizard self-driving` — the program the self-driving onboarding runs. */
export const SELF_DRIVING_WORKFLOW_ID = 'self-driving'

/**
 * Which wizard program a surface is tracking. Defaulted rather than required so every existing
 * consumer keeps watching the SDK install without passing anything.
 */
export function resolveWorkflowId(workflowId?: string): string {
    return workflowId ?? POSTHOG_INTEGRATION_WORKFLOW_ID
}
