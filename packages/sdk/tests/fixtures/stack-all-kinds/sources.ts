import { endpoint, secret, source, sql } from '@posthog/sdk/define'

import { mrr } from './models/models'

export const billingDatabase = source('billing_db', {
    source_type: 'Postgres',
    prefix: 'billing_',
    payload: { host: 'db.example.com', port: 5432, database: 'billing', user: 'posthog', password: secret('BILLING_DB_PASSWORD') },
})

export const accountRevenue = endpoint('account-revenue', {
    description: 'MRR by account and month, for the in-app billing page.',
    query: sql`
        select account_id, month, mrr_usd
        from ${mrr}
        order by account_id, month`,
})
