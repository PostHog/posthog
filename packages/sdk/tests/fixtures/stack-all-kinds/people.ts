import { action, cohort } from '@posthog/sdk/define'

import { checkoutCompleted } from './events'

export const payingCustomers = cohort('paying_customers', {
    name: 'Paying customers',
    filters: {
        properties: {
            type: 'OR',
            values: [{ type: 'AND', values: [{ key: 'plan', type: 'person', value: ['team', 'scale'], operator: 'exact' }] }],
        },
    },
})

export const purchased = action('purchased', {
    name: 'Purchased',
    steps: [{ event: checkoutCompleted }],
})
