import { event, prop } from '@posthog/sdk/define'

export const checkoutCompleted = event('checkout_completed', {
    description: 'A customer paid for an order. Sent by the server after the payment provider confirms.',
    tags: ['payments'],
    enforcement: 'reject',
    properties: {
        account_id: prop.string().required(),
        order_id: prop.string().required(),
        total_usd: prop.number().required().describe('Order total after discounts'),
        plan: prop.enum(['free', 'team', 'scale']),
        paid_at: prop.datetime(),
    },
})

export const planUpgraded = event('plan_upgraded', {
    description: 'An account moved to a higher plan.',
    properties: {
        account_id: prop.string().required(),
        from_plan: prop.enum(['free', 'team']).required(),
        trial: prop.boolean(),
    },
})
