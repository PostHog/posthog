import { dashboard, text, trend } from '@posthog/sdk/define'

import { checkoutCompleted as checkout } from './events'
import { mrr } from './models/models'

const plans = ['free', 'team', 'scale'] as const

export const revenue = dashboard('revenue', {
    name: 'Revenue',
    tiles: [
        trend(mrr, { sum: 'mrr_usd', interval: 'month' }),
        ...plans.map((plan) => trend(checkout, { where: { plan }, interval: 'week' })),
        text('Revenue is recognised when the payment provider confirms the checkout.'),
    ],
})
