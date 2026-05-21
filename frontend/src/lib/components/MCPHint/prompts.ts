export const SURFACE_KEYS = [
    'feature_flags.create',
    'feature_flags.update',
    'experiments.create',
    'experiments.launch',
    'dashboards.create',
    'insights.create',
    'surveys.create',
    'alerts.create',
    'cohorts.create',
    'actions.create',
    'annotations.create',
    'error_tracking.assign',
    'early_access_features.create',
    'sql.execute',
    'workflows.create',
] as const

export type SurfaceKey = (typeof SURFACE_KEYS)[number]

export type SurfacePrompts = {
    toast: string
    examples: string[]
}

export const SURFACE_PROMPTS: Record<SurfaceKey, SurfacePrompts> = {
    'feature_flags.create': {
        toast: '"Create a feature flag called new-checkout rolled out to 20% of users"',
        examples: [
            '"Create a feature flag for the new pricing page"',
            '"Roll out checkout-v2 to 25% of EU users"',
            '"Schedule pricing-flag to enable Friday at noon"',
        ],
    },
    'feature_flags.update': {
        toast: '"Bump rollout for new-checkout to 50%"',
        examples: [
            '"Bump rollout for new-checkout to 50%"',
            '"Disable beta-banner flag"',
            '"Add eu-only condition to pricing-flag"',
        ],
    },
    'experiments.create': {
        toast: '"Create an A/B experiment for the new pricing page"',
        examples: [
            '"Create an A/B experiment for the new pricing page"',
            '"Launch a multivariate test on the signup CTA"',
            '"Set up an experiment to measure checkout conversion"',
        ],
    },
    'experiments.launch': {
        toast: '"Launch experiment pricing-test"',
        examples: [
            '"Launch experiment pricing-test"',
            '"Archive the old signup-cta experiment"',
            '"Check the results of checkout-flow-v2"',
        ],
    },
    'dashboards.create': {
        toast: '"Build a retention dashboard for signups last 30 days"',
        examples: [
            '"Build a retention dashboard for signups last 30 days"',
            '"Make me a dashboard tracking checkout funnel drop-off"',
            '"Add a revenue tile to the executive dashboard"',
        ],
    },
    'insights.create': {
        toast: '"Run a trends query for signup_completed last 30 days"',
        examples: [
            '"Show me sign-up trends for the last 30 days"',
            '"Build a funnel for the onboarding flow"',
            '"Compute retention by week for paid users"',
        ],
    },
    'surveys.create': {
        toast: '"Create an NPS survey targeted at paid users"',
        examples: [
            '"Create an NPS survey targeted at paid users"',
            '"Ask churned users why they left"',
            '"Launch a feedback survey on the new dashboard"',
        ],
    },
    'alerts.create': {
        toast: '"Alert me if signups drop more than 20% week over week"',
        examples: [
            '"Alert me if signups drop more than 20% week over week"',
            '"Notify the team when checkout errors spike"',
            '"Set up a daily revenue threshold alert"',
        ],
    },
    'cohorts.create': {
        toast: '"Build a cohort of users who signed up last week and never returned"',
        examples: [
            '"Build a cohort of users who signed up last week and never returned"',
            '"Make a cohort of EU paid customers"',
            '"Add these users to the beta-testers cohort"',
        ],
    },
    'actions.create': {
        toast: '"Create an action for clicks on the upgrade button"',
        examples: [
            '"Create an action for clicks on the upgrade button"',
            '"Define a pageview action for the pricing page"',
            '"Make an action that fires when users complete onboarding"',
        ],
    },
    'annotations.create': {
        toast: '"Annotate today as the launch of v2 checkout"',
        examples: [
            '"Annotate today as the launch of v2 checkout"',
            '"Mark the deploy on the conversion dashboard"',
            '"Add a release note to last Tuesday"',
        ],
    },
    'error_tracking.assign': {
        toast: '"Assign all TypeError issues to the frontend team"',
        examples: [
            '"Assign all TypeError issues to the frontend team"',
            '"Show me the top 10 unresolved errors this week"',
            '"Set up an assignment rule for billing-related errors"',
        ],
    },
    'early_access_features.create': {
        toast: '"Create an early-access feature for the new editor"',
        examples: [
            '"Create an early-access feature for the new editor"',
            '"Promote ai-suggestions to general availability"',
            '"Show me everyone signed up for the v2 beta"',
        ],
    },
    'sql.execute': {
        toast: '"Run this SQL: select count() from events where event = $pageview"',
        examples: [
            '"How many users viewed the pricing page yesterday?"',
            '"What\'s our DAU trend for the last 90 days?"',
            '"Find the top 20 most active teams this week"',
        ],
    },
    'workflows.create': {
        toast: '"Build a workflow that emails new signups a welcome message after 1 day"',
        examples: [
            '"Build a workflow that emails new signups a welcome message after 1 day"',
            '"Send a Slack alert when a paid user hits the error_rate threshold"',
            '"Trigger a reminder push 7 days after onboarding starts but never completes"',
        ],
    },
}
