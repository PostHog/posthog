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
    }),
})
