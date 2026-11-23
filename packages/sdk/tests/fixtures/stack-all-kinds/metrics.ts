import { check, metric } from '@posthog/sdk/define'

import { mrr } from './models/models'

export const totalMrr = metric('total_mrr', {
    description: 'Sum of monthly recurring revenue across accounts.',
    unit: 'USD',
    from: mrr,
    aggregate: 'sum',
    column: 'mrr_usd',
    dimensions: ['plan'],
})

export const mrrAccountsPresent = check('mrr_account_id_not_null', {
    name: 'mrr_account_id_not_null',
    description: 'Every MRR row names an account.',
    subject: mrr,
    column_name: 'account_id',
    check_type: 'not_null',
    severity: 'error',
})
