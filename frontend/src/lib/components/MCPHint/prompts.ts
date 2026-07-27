import { UserRole } from '~/types'

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
    'data_warehouse_sources.create',
    'data_warehouse_sources.update',
] as const

export type SurfaceKey = (typeof SURFACE_KEYS)[number]

export type SurfacePrompts = {
    toast: string
    examples: string[]
}

export const FALLBACK_PROMPTS: Record<SurfaceKey, SurfacePrompts> = {
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
    'data_warehouse_sources.create': {
        toast: '"Connect a Stripe source and sync invoices daily"',
        examples: [
            '"Connect a Stripe source and sync invoices daily"',
            '"Import my Postgres orders table incrementally"',
            '"Set up a Hubspot source for contacts and companies"',
        ],
    },
    'data_warehouse_sources.update': {
        toast: '"Update the credentials on my Stripe source"',
        examples: [
            '"Update the credentials on my Stripe source"',
            '"Resync the orders table on my Postgres source"',
            '"Switch my Stripe source to sync hourly"',
        ],
    },
}

// Roles we tailor prompts for. Not every role is catered to; fallback to defaults for `sales`, `other`, and null.
export const TAILORED_ROLES = [
    UserRole.Founder,
    UserRole.Product,
    UserRole.Leadership,
    UserRole.Marketing,
    UserRole.Engineering,
    UserRole.Data,
] as const satisfies UserRole[]
export type TailoredRole = (typeof TAILORED_ROLES)[number]

function isTailoredRole(role: string | null | undefined): role is TailoredRole {
    return typeof role === 'string' && (TAILORED_ROLES as readonly string[]).includes(role)
}

const PROMPT_OVERRIDES: Record<TailoredRole, Partial<Record<SurfaceKey, SurfacePrompts>>> = {
    founder: {
        'dashboards.create': {
            toast: '"Build me an exec dashboard: MRR, MAU, churn, and the top events this month"',
            examples: [
                '"Build an exec dashboard: MRR, MAU, churn, top events"',
                '"Show me everything I need to know before the next board call"',
                '"Compare this month\'s funnel against last month"',
            ],
        },
        'insights.create': {
            toast: '"Show me weekly active users for the last 90 days"',
            examples: [
                '"Weekly active users for the last 90 days"',
                '"Funnel: signup → activated → paid for the last quarter"',
                '"Revenue trend by plan since launch"',
            ],
        },
        'alerts.create': {
            toast: '"Alert me if MAU drops more than 10% week over week"',
            examples: [
                '"Alert me if MAU drops more than 10% week over week"',
                '"Notify me when a customer over $1k MRR churns"',
                '"Tell me if daily signups dip below the 7-day rolling average"',
            ],
        },
        'surveys.create': {
            toast: '"Run an NPS survey on all paid customers"',
            examples: [
                '"Run an NPS survey on all paid customers"',
                '"Ask churned users in one question why they left"',
                '"Survey: would you recommend us to another founder?"',
            ],
        },
        'data_warehouse_sources.create': {
            toast: '"Connect Stripe and sync invoices and subscriptions daily"',
            examples: [
                '"Connect Stripe and sync invoices and subscriptions daily"',
                '"Import Stripe charges so I can track MRR in PostHog"',
                '"Set up Stripe to see revenue next to product usage"',
            ],
        },
        'data_warehouse_sources.update': {
            toast: '"Sync my Stripe source hourly so revenue stays fresh"',
            examples: [
                '"Sync my Stripe source hourly so revenue stays fresh"',
                '"Resync this month\'s Stripe invoices"',
                '"Update the credentials on my Stripe source"',
            ],
        },
    },
    product: {
        'feature_flags.create': {
            toast: '"Create a flag for the new pricing page rolled out to 25% of users"',
            examples: [
                '"Create a flag for the new pricing page, 25% of users"',
                '"Multivariate flag for the upgrade CTA copy"',
                '"Roll out the new editor to internal users only"',
            ],
        },
        'experiments.create': {
            toast: '"A/B test the redesigned onboarding flow"',
            examples: [
                '"A/B test the redesigned onboarding flow"',
                '"Multivariate test the upgrade CTA copy"',
                '"Run an experiment on the new empty state"',
            ],
        },
        'insights.create': {
            toast: '"Build a funnel for the new onboarding flow"',
            examples: [
                '"Build a funnel for the new onboarding flow"',
                '"Week-1 retention split by acquisition channel"',
                '"Trend signups by referrer for the last 30 days"',
            ],
        },
        'surveys.create': {
            toast: '"Run a PMF survey on activated users"',
            examples: [
                '"Run a PMF survey on activated users"',
                '"Ask power users which feature they\'d hate to lose"',
                '"Launch a feedback survey on the new editor"',
            ],
        },
        'early_access_features.create': {
            toast: '"Open the new editor as an early-access feature"',
            examples: [
                '"Open the new editor as an early-access feature"',
                '"Promote ai-suggestions to GA and show me who\'s opted in"',
                '"Pull the list of people in the v2 beta"',
            ],
        },
        'data_warehouse_sources.create': {
            toast: '"Connect Postgres and sync the subscriptions table incrementally"',
            examples: [
                '"Connect Postgres and sync the subscriptions table incrementally"',
                '"Import my product roadmap from a Google Sheet"',
                '"Set up a Postgres source for the accounts table"',
            ],
        },
        'data_warehouse_sources.update': {
            toast: '"Resync my Google Sheet after I updated the roadmap"',
            examples: [
                '"Resync my Google Sheet after I updated the roadmap"',
                '"Sync my Postgres accounts table hourly"',
                '"Switch my Postgres source to incremental sync on updated_at"',
            ],
        },
    },
    leadership: {
        'dashboards.create': {
            toast: '"One-glance dashboard: revenue, MAU, churn, support backlog"',
            examples: [
                '"One-glance dashboard: revenue, MAU, churn, support backlog"',
                '"Build me a board-meeting dashboard for this quarter"',
                '"Add a revenue tile to the executive dashboard"',
            ],
        },
        'alerts.create': {
            toast: '"Alert me when revenue dips below the 4-week rolling average"',
            examples: [
                '"Alert me when revenue dips below the 4-week rolling average"',
                '"Notify the leadership channel when churn doubles week over week"',
                '"Daily threshold alert on net new paid customers"',
            ],
        },
        'insights.create': {
            toast: '"Show MAU growth over the last 4 quarters"',
            examples: [
                '"MAU growth over the last 4 quarters"',
                '"Where is our funnel leaking the most volume?"',
                '"Which features drive the most upgrades?"',
            ],
        },
    },
    marketing: {
        'surveys.create': {
            toast: '"NPS survey for users who clicked our last newsletter"',
            examples: [
                '"NPS survey for users who clicked our last newsletter"',
                '"Ask churned users why, in one short question"',
                '"Feedback survey on the new landing page"',
            ],
        },
        'cohorts.create': {
            toast: '"Build a cohort of paid users in Germany who NPS\'d 6 or lower"',
            examples: [
                '"Cohort of users who saw pricing but didn\'t sign up"',
                '"Cohort of paid users in Germany who NPS\'d 6 or lower"',
                '"Tag everyone who signed up from the LinkedIn campaign"',
            ],
        },
        'experiments.create': {
            toast: '"A/B test the landing page hero copy"',
            examples: [
                '"A/B test the landing page hero copy"',
                '"Run an experiment on the upgrade CTA color"',
                '"Multivariate test the email subject line"',
            ],
        },
        'annotations.create': {
            toast: '"Annotate today as the launch of the new landing page"',
            examples: [
                '"Annotate today as the launch of the new landing page"',
                '"Mark when the spring email blast went out"',
                '"Add a release note: paid search budget doubled"',
            ],
        },
        'dashboards.create': {
            toast: '"Marketing dashboard: signups by source, CAC by channel, top campaigns"',
            examples: [
                '"Signups by source, CAC by channel, top-performing campaigns"',
                '"Build a content funnel: visit → trial → paid by referrer"',
                '"Track LinkedIn-sourced users from signup to activation"',
            ],
        },
        'data_warehouse_sources.create': {
            toast: '"Connect Google Ads and sync campaign spend daily"',
            examples: [
                '"Connect Google Ads and sync campaign spend daily"',
                '"Import Meta Ads and LinkedIn Ads to compare channel ROI"',
                '"Set up Hubspot to sync marketing contacts"',
            ],
        },
        'data_warehouse_sources.update': {
            toast: '"Sync my Google Ads spend hourly"',
            examples: [
                '"Sync my Google Ads spend hourly"',
                '"Resync this week\'s Meta Ads campaigns"',
                '"Also start syncing conversions from my Google Ads source"',
            ],
        },
    },
    engineering: {
        'feature_flags.create': {
            toast: '"Add a kill-switch flag for the checkout v2 release"',
            examples: [
                '"Add a kill-switch flag for the checkout v2 release"',
                '"Flag eu-rollout for users in DE, FR, IT"',
                '"Multivariate flag for the new editor UI"',
            ],
        },
        'feature_flags.update': {
            toast: '"List flags rolled out to 100% — they\'re probably dead code"',
            examples: [
                '"List flags rolled out to 100% (probably safe to delete)"',
                '"Disable experiment-checkout — the experiment is over"',
                '"Bump beta-feature flag from 10% to 25%"',
            ],
        },
        'actions.create': {
            toast: '"Define an action for clicks on the upgrade CTA"',
            examples: [
                '"Action for clicks on the upgrade CTA"',
                '"Pageview action for /pricing"',
                '"Action that fires on $autocapture for the signup form"',
            ],
        },
        'error_tracking.assign': {
            toast: '"Assign all TypeError issues to the frontend team"',
            examples: [
                '"Assign every billing-related error to the payments team"',
                '"Show unresolved errors that fired more than 100 times this week"',
                '"Auto-assign anything matching auth.* to the platform team"',
            ],
        },
        'sql.execute': {
            toast: '"How many users hit a 500 in the last hour?"',
            examples: [
                '"How many users hit a 500 in the last hour?"',
                '"Find the 10 slowest queries from the last 7 days"',
                '"Which events haven\'t fired in 30 days? Probably dead instrumentation."',
            ],
        },
        'alerts.create': {
            toast: '"Page me if 5xx error rate exceeds 1% over 5 minutes"',
            examples: [
                '"Page me if 5xx error rate exceeds 1% over 5 minutes"',
                '"Alert when checkout failure rate spikes 3x baseline"',
                '"Notify Slack when ingestion lag exceeds 30 seconds"',
            ],
        },
        'workflows.create': {
            toast: '"Send a Slack alert when a paid user hits the error_rate threshold"',
            examples: [
                '"Send a Slack alert when a paid user hits the error_rate threshold"',
                '"Trigger a PagerDuty page when ingestion lag exceeds 60s"',
                '"Auto-create a Jira ticket when a new critical error appears"',
            ],
        },
        'data_warehouse_sources.create': {
            toast: '"Connect our production Postgres and sync the orders table incrementally"',
            examples: [
                '"Connect our production Postgres and sync orders incrementally"',
                '"Set up a Stripe source and sync charges hourly"',
                '"Import the users table from MySQL with a staging prefix"',
            ],
        },
        'data_warehouse_sources.update': {
            toast: '"Rotate the credentials on our production Postgres source"',
            examples: [
                '"Rotate the credentials on our production Postgres source"',
                '"Point my Postgres source at the new read replica"',
                '"Resync the orders table after the schema migration"',
            ],
        },
    },
    data: {
        'sql.execute': {
            toast: '"Retention curve for paid users by signup month"',
            examples: [
                '"Retention curve for paid users by signup month"',
                '"Top 20 events by volume in the last 24 hours"',
                '"DAU split by primary plan tier over the last 90 days"',
            ],
        },
        'insights.create': {
            toast: '"Compute retention by week for paid users on the new plan"',
            examples: [
                '"Retention by week for paid users on the new plan"',
                '"Funnel: signup → activated → first power feature → paid"',
                '"Trend $pageview broken down by referring domain"',
            ],
        },
        'cohorts.create': {
            toast: '"Build a cohort of power users — 5+ sessions a week over the last month"',
            examples: [
                '"Cohort of power users (5+ sessions per week, last 4 weeks)"',
                '"Cohort of users who signed up but never returned"',
                '"Cohort of users who hit a 500 error in the last 7 days"',
            ],
        },
        'dashboards.create': {
            toast: '"Data quality dashboard: events per hour, ingestion lag, error rate"',
            examples: [
                '"Data quality dashboard: events/hour, ingestion lag, error rate"',
                '"Retention curves by signup-month cohort"',
                '"Churn-prediction dashboard for paid plans"',
            ],
        },
        'data_warehouse_sources.create': {
            toast: '"Connect Snowflake and sync the fct_orders table incrementally"',
            examples: [
                '"Connect Snowflake and sync fct_orders incrementally"',
                '"Import the Stripe charges table and join it to events in SQL"',
                '"Set up a Postgres source for the dim_users table"',
            ],
        },
        'data_warehouse_sources.update': {
            toast: '"Switch my Postgres source to incremental sync on updated_at"',
            examples: [
                '"Switch my Postgres source to incremental sync on updated_at"',
                '"Bump the Stripe source to sync hourly"',
                '"Resync the orders table from Snowflake"',
            ],
        },
    },
}

export interface ResolveOptions {
    /** From `user.role_at_organization`. Unknown / `sales` / `other` falls back to defaults. */
    role?: string | null
    /**
     * For `sql.execute` only: the team's most-recent or most-popular event names. When present,
     * examples are rewritten to reference real event names so the user recognizes them.
     */
    topEvents?: string[]
}

function buildSqlExamplesFromEvents(topEvents: string[]): string[] {
    // Filter out PostHog-internal events (lead with `$`) so we surface the user's own product events,
    // also be conservative to avoid surface events that look like SQL injection vectors.
    const owned = topEvents
        .filter((name) => name && !name.startsWith('$') && /^[A-Za-z0-9_.:-]{1,80}$/.test(name))
        .slice(0, 3)
    if (owned.length === 0) {
        return []
    }

    const [first, second] = owned
    const funnelSteps = owned.join(' → ')

    return [
        `"How many users triggered ${first} yesterday?"`,
        second && `"What's the trend of ${second} over the last 30 days?"`,
        owned.length >= 2 && `"Funnel: ${funnelSteps}"`,
    ].filter(Boolean) as string[]
}

export function getSurfacePrompts(surfaceKey: SurfaceKey, options: ResolveOptions = {}): SurfacePrompts {
    const defaults = FALLBACK_PROMPTS[surfaceKey]
    const role = options.role
    const roleOverride = isTailoredRole(role) ? (PROMPT_OVERRIDES[role]?.[surfaceKey] ?? {}) : {}
    const merged: SurfacePrompts = { ...defaults, ...roleOverride }

    if (surfaceKey === 'sql.execute' && options.topEvents && options.topEvents.length > 0) {
        const dynamicExamples = buildSqlExamplesFromEvents(options.topEvents)
        if (dynamicExamples.length > 0) {
            merged.examples = dynamicExamples
        }
    }

    return merged
}

/**
 * Wraps a caller-supplied dynamic toast prompt in straight double quotes to match the static defaults.
 * Strips existing wrapping quotes first so passing `"foo"` or `foo` both render as `"foo"`.
 */
export function formatDerivedToastPrompt(prompt: string): string {
    const trimmed = prompt.trim().replace(/^["']|["']$/g, '')
    return `"${trimmed}"`
}
