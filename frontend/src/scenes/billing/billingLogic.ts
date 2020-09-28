import { kea } from 'kea'
import api from 'lib/api'

export const billingLogic = kea({
    loaders: () => ({
        plans: [
            [],
            {
                loadPlans: async () => {
                    return await api.get('plans?self_serve=1')
                },
            },
        ],
        billingSubscription: [
            {},
            {
                subscribe: async (plan) => {
                    return await api.create('billing/subscribe', { plan })
                },
            },
        ],
    }),
})
