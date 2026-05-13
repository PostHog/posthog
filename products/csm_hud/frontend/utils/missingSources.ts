export type MissingSourceKind = 'vitally' | 'zendesk' | 'salesforce' | 'internal-billing'

const TABLE_TO_SOURCE: Record<string, MissingSourceKind> = {
    vitally_accounts: 'vitally',
    vitally_notes: 'vitally',
    vitally_tasks: 'vitally',
    vitally_users: 'vitally',
    zendesk_tickets: 'zendesk',
    'salesforce.opportunity': 'salesforce',
    customer_billing_summary: 'internal-billing',
    prod_postgres_billing_upcominginvoice: 'internal-billing',
    iwa_org_month_product_mrr_usage: 'internal-billing',
    billing_customers_with_owner: 'internal-billing',
    'postgres.revenue.charge': 'internal-billing',
    revenuepostgres_invoice: 'internal-billing',
}

const SOURCE_KIND_FOR_NEW_SOURCE_LINK: Partial<Record<MissingSourceKind, string>> = {
    vitally: 'Vitally',
    zendesk: 'Zendesk',
    salesforce: 'Salesforce',
    // internal-billing has no public-facing connector
}

const SOURCE_LABEL: Record<MissingSourceKind, string> = {
    vitally: 'Vitally',
    zendesk: 'Zendesk',
    salesforce: 'Salesforce',
    'internal-billing': 'PostHog internal billing data',
}

const SOURCE_DESCRIPTION: Record<MissingSourceKind, string> = {
    vitally: 'Account health, segments, key roles, notes, and tasks.',
    zendesk: 'Support ticket counts and conversation health.',
    salesforce: 'Contract dates, ARR, and renewal forecast.',
    'internal-billing':
        'Billing period dates, MRR history, Stripe charges, and invoice subtotals. Only available where PostHog ops syncs the internal billing Postgres (prod team 2).',
}

/**
 * Parse "Unknown table `X`" out of a HogQL error envelope and return the
 * source-of-record that table comes from. Returns null for any other shape so
 * unrelated errors still surface to the user.
 */
export function detectMissingSources(error: unknown): MissingSourceKind[] {
    const message =
        error instanceof Error
            ? error.message
            : typeof error === 'string'
              ? error
              : ((error as { detail?: string; message?: string })?.detail ??
                (error as { message?: string })?.message ??
                '')
    if (!message || !message.includes('Unknown table')) {
        return []
    }
    const sources = new Set<MissingSourceKind>()
    for (const [table, source] of Object.entries(TABLE_TO_SOURCE)) {
        if (message.includes(`\`${table}\``)) {
            sources.add(source)
        }
    }
    return Array.from(sources)
}

export function sourceLabel(source: MissingSourceKind): string {
    return SOURCE_LABEL[source]
}

export function sourceDescription(source: MissingSourceKind): string {
    return SOURCE_DESCRIPTION[source]
}

/** New-source kind param for `urls.dataWarehouseSourceNew(kind)`; null for sources that aren't user-connectable. */
export function newSourceKind(source: MissingSourceKind): string | null {
    return SOURCE_KIND_FOR_NEW_SOURCE_LINK[source] ?? null
}
