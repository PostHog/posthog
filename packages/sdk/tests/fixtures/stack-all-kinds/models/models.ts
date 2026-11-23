import { file, model, sql } from '@posthog/sdk/define'

import { checkoutCompleted as checkout } from '../events'

export const mrr = model('mrr', {
    description: 'Monthly recurring revenue per account, from confirmed checkouts.',
    materialize: '1hour',
    columns: { account_id: 'string', month: 'date', mrr_usd: 'number', plan: 'string' },
    query: sql`
        select ${checkout.props.account_id} as account_id,
               toStartOfMonth(timestamp) as month,
               sum(${checkout.props.total_usd}) as mrr_usd,
               any(${checkout.props.plan}) as plan
        from events
        where event = ${checkout}
        group by account_id, month`,
})

export const churnedAccounts = model('churned_accounts', {
    description: 'Accounts with no checkout in the last 60 days.',
    columns: { account_id: 'string', last_checkout: 'datetime' },
    query: file('./churned_accounts.sql'),
})

export const mrrByPlan = model('mrr_by_plan', {
    description: 'Monthly recurring revenue per plan, from the MRR model.',
    columns: { month: 'date', plan: 'string', mrr_usd: 'number' },
    query: sql`
        select month, plan, sum(mrr_usd) as mrr_usd
        from ${mrr}
        group by month, plan`,
})
