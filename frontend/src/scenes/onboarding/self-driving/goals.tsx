/**
 * The goals a user can declare when entering the self-driving onboarding. Each goal is modeled as
 * something that is clearly achieved or not: `done` names the observable finish line the flow
 * drives toward (and what time-to-goal is measured against). Nothing downstream consumes the
 * selection yet - this step only records the declared intent.
 */

export type SelfDrivingGoal = 'user_behavior' | 'fix_issues' | 'website_traffic' | 'ai_app'

export interface SelfDrivingGoalDefinition {
    key: SelfDrivingGoal
    title: string
    /** One sentence: how agents get there, ending in the deliverable (the goal's finish line). */
    description: string
    /** The achievement criterion (measurement spec, not rendered): the observable event that marks the goal done. */
    done: string
    /** Product icon key for `iconForType`. */
    iconType: 'product_analytics' | 'error_tracking' | 'web_analytics' | 'llm_analytics'
}

export const SELF_DRIVING_GOALS: SelfDrivingGoalDefinition[] = [
    {
        key: 'user_behavior',
        title: 'See how people use my product',
        description: 'Agents watch your events and sessions, and deliver your first report on real usage.',
        done: 'first behavior insight or report with real data',
        iconType: 'product_analytics',
    },
    {
        key: 'fix_issues',
        title: 'Fix a real issue in my product',
        description: 'Agents turn errors and broken sessions into signals, and open the first fix as a pull request.',
        done: 'first agent-opened fix pull request',
        iconType: 'error_tracking',
    },
    {
        key: 'website_traffic',
        title: 'See my website traffic',
        description: 'Traffic, sources, and conversion on a live dashboard as soon as data arrives.',
        done: 'web analytics dashboard showing real pageviews',
        iconType: 'web_analytics',
    },
    {
        key: 'ai_app',
        title: 'See what my AI app is doing',
        description: 'Traces, costs, and failures from your LLM features, from the first trace in.',
        done: 'first AI traces ingested',
        iconType: 'llm_analytics',
    },
]
