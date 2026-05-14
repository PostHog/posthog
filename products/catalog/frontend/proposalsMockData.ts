import { Proposal } from './proposalTypes'

// Fixtures only used in the hackathon prototype.
// Edit freely to demo different shapes; nothing here hits a backend.
export const MOCK_PROPOSALS: Proposal[] = [
    {
        id: 'p_arr',
        kind: 'new_definition',
        title: 'Annual Recurring Revenue (ARR)',
        summary: 'Derived from stripe.subscription + 7 insights',
        ageHours: 2,
        confidence: 0.92,
        status: 'open',
        provenance: [
            {
                source: 'stripe.subscription',
                detail: 'fields: amount, status, billing_interval',
            },
            {
                source: '7 product insights',
                detail: 'most-used filter: status = active',
            },
            {
                source: 'data_warehouse.stripe_customers',
                detail: 'identity stitched via customer_id',
            },
        ],
        impact: { insights: 0, dashboards: 0, consumers: [] },
        suggestedReviewers: ['sarah@', 'finance-ops@'],
        definition: {
            name: 'arr',
            kind: 'metric',
            description:
                'Annual Recurring Revenue across all active Stripe subscriptions, normalized to a yearly cadence.',
            formulaPlainEnglish:
                'Sum of subscription amount where status is active, multiplied by 12 for monthly subscriptions, by 1 for yearly subscriptions.',
            formulaSql:
                "SELECT\n    SUM(\n        CASE\n            WHEN billing_interval = 'month' THEN amount * 12\n            WHEN billing_interval = 'year' THEN amount\n        END\n    ) AS arr\nFROM stripe.subscription\nWHERE status = 'active'",
            suggestedDimensions: ['plan', 'country', 'cohort_month'],
            suggestedOwner: 'sarah@',
            entity: 'Subscription',
        },
    },
    {
        id: 'p_drift_revenue',
        kind: 'drift',
        title: 'revenue formula diverged from Stripe schema',
        summary: 'Stripe added `discount_amount`; current metric ignores it',
        ageHours: 5,
        confidence: 0.88,
        status: 'open',
        provenance: [
            { source: 'stripe.invoice', detail: 'new column added 2026-05-10' },
            {
                source: 'definition: revenue',
                detail: 'last updated 2025-11-02',
            },
        ],
        impact: {
            insights: 12,
            dashboards: 3,
            consumers: ['Finance dashboard', 'Weekly board update', 'MRR breakdown'],
        },
        suggestedReviewers: ['sarah@'],
        targetDefinition: 'revenue',
        targetKind: 'metric',
        triggerEvent: 'Stripe added `discount_amount` column on 2026-05-10',
        diff: [
            {
                field: 'description',
                before: 'Total recognized revenue from Stripe invoices.',
                after: 'Total recognized revenue from Stripe invoices, net of discounts.',
            },
            {
                field: 'formula',
                before: 'SUM(invoice.amount_paid)',
                after: 'SUM(invoice.amount_paid - invoice.discount_amount)',
            },
        ],
    },
    {
        id: 'p_dup_mrr',
        kind: 'duplicate',
        title: '3 likely duplicate MRR metrics',
        summary: 'mrr, monthly_recurring_revenue, MRR — same formula, different names',
        ageHours: 8,
        confidence: 0.95,
        status: 'open',
        provenance: [
            {
                source: 'cross-team scan',
                detail: 'matching formulas across 3 owners',
            },
            {
                source: 'usage telemetry',
                detail: '4, 11 and 2 insights respectively',
            },
        ],
        impact: { insights: 17, dashboards: 5 },
        suggestedReviewers: ['data-platform@'],
        recommendedCanonicalIndex: 1,
        candidates: [
            {
                id: 'def_mrr_legacy',
                name: 'mrr',
                description: 'Legacy MRR — sum of monthly subscriptions',
                owner: 'alex@',
                usage: 4,
            },
            {
                id: 'def_mrr_canon',
                name: 'monthly_recurring_revenue',
                description: 'Standard MRR — sum of monthly-normalized active subscriptions',
                owner: 'sarah@',
                usage: 11,
            },
            {
                id: 'def_mrr_export',
                name: 'MRR',
                description: 'MRR used in the board export pipeline',
                owner: 'finance-ops@',
                usage: 2,
            },
        ],
    },
    {
        id: 'p_schema_stripe',
        kind: 'schema_sync',
        title: 'Stripe added 4 new columns on `subscription`',
        summary: 'Propose 3 as dimensions, 1 as foreign key',
        ageHours: 14,
        confidence: 0.81,
        status: 'open',
        provenance: [
            {
                source: 'stripe webhook schema diff',
                detail: 'detected 2026-05-12 03:14 UTC',
            },
        ],
        suggestedReviewers: ['data-platform@'],
        sourceTable: 'stripe.subscription',
        addedColumns: [
            {
                column: 'trial_end',
                type: 'timestamp',
                suggestedRole: 'dimension',
                preselected: true,
            },
            {
                column: 'collection_method',
                type: 'varchar',
                suggestedRole: 'dimension',
                preselected: true,
            },
            {
                column: 'default_payment_method',
                type: 'varchar',
                suggestedRole: 'foreign_key',
                preselected: false,
            },
            {
                column: 'metadata_internal_team',
                type: 'jsonb',
                suggestedRole: 'dimension',
                preselected: false,
            },
        ],
    },
    {
        id: 'p_rel_identity',
        kind: 'relationship',
        title: 'Stitch PostHog person ↔ Stripe customer',
        summary: '94% of distinct_ids match a Stripe customer_email',
        ageHours: 6,
        confidence: 0.94,
        status: 'open',
        provenance: [
            {
                source: 'identity sampling',
                detail: '50k persons compared with stripe.customer',
            },
            {
                source: 'existing SQL views',
                detail: '2 saved queries already join on email',
            },
        ],
        leftSide: { entity: 'Person', field: 'email' },
        rightSide: { entity: 'StripeCustomer', field: 'email' },
        relationshipType: 'one_to_one',
        suggestedReviewers: ['data-platform@'],
        sampleMatches: [
            { left: 'sarah@example.com', right: 'cus_NwzZ…sarah' },
            { left: 'mark@acme.io', right: 'cus_LkjP…mark' },
            { left: 'pat+demo@hog.dev', right: 'cus_QqRr…pat' },
        ],
    },
    {
        id: 'p_meta_batch',
        kind: 'metadata',
        title: '15 description and synonym improvements',
        summary: 'Across User, Subscription and Order entities',
        ageHours: 22,
        confidence: 0.97,
        status: 'open',
        provenance: [
            {
                source: 'glossary scan',
                detail: 'compared current descriptions vs upstream column comments',
            },
        ],
        targetDefinition: '(multiple)',
        targetKind: 'dimension',
        changes: [
            {
                field: 'User.plan_tier — description',
                before: 'plan tier',
                after: 'The active subscription tier for the user — one of free, growth, or enterprise.',
            },
            {
                field: 'Order.placed_at — synonyms',
                before: '—',
                after: 'order_date, purchase_at, checkout_completed_at',
            },
            {
                field: 'Subscription.mrr — description',
                before: 'MRR',
                after: 'Monthly recurring revenue attributable to this subscription, normalized to a single month.',
            },
        ],
    },
    {
        id: 'p_question_identity',
        kind: 'question',
        title: 'Which field identifies a Customer across sources?',
        summary: 'Agent needs your input before proposing the Customer entity',
        ageHours: 1,
        confidence: 0.65,
        status: 'open',
        provenance: [
            {
                source: 'identity ambiguity',
                detail: 'found 3 plausible identifiers',
            },
        ],
        question:
            'I see Person (PostHog), StripeCustomer (Stripe) and HubSpotContact (HubSpot). Which field should I treat as the canonical Customer identifier when building the Customer entity?',
        options: [
            {
                id: 'opt_email',
                label: 'email',
                rationale: '94% of records match across all three sources via email; weakest against SSO renaming.',
            },
            {
                id: 'opt_distinct_id',
                label: 'PostHog distinct_id',
                rationale: 'Cleanest in product analytics; only 61% match into Stripe.',
            },
            {
                id: 'opt_external',
                label: 'External UUID set in Stripe metadata',
                rationale:
                    'Only 38% of Stripe customers carry it today, but it would be the canonical option going forward.',
            },
        ],
        allowFreeform: true,
    },
    // A rejected example so the "Recently rejected" view has content.
    {
        id: 'p_reject_lifetime_revenue',
        kind: 'new_definition',
        title: 'Lifetime revenue per user',
        summary: 'Rejected — duplicates `ltv`, kept for audit',
        ageHours: 26,
        confidence: 0.72,
        status: 'rejected',
        rejectionReason:
            'We already have an `ltv` metric owned by finance. Closer to a duplicate than a new definition.',
        provenance: [
            {
                source: 'stripe.invoice',
                detail: 'sum of amount_paid by customer',
            },
            { source: 'posthog.person', detail: 'unique customer count' },
        ],
        suggestedReviewers: ['sarah@'],
        definition: {
            name: 'lifetime_revenue_per_user',
            kind: 'metric',
            description: 'Lifetime revenue per unique paying user.',
            formulaPlainEnglish: 'Sum of invoice.amount_paid divided by unique paying customers.',
            formulaSql:
                'SELECT SUM(amount_paid) / COUNT(DISTINCT customer_id) AS lifetime_revenue_per_user FROM stripe.invoice',
            entity: 'Customer',
        },
    },
]

export const ACCEPTANCE_STATS = {
    approved30d: 47,
    rejected30d: 8,
    edited30d: 3,
    acceptRate: 0.91,
}
