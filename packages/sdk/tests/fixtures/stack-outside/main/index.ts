import { alert } from '@posthog/sdk/define'

import { shared } from '../shared/insights'

export const watch = alert('watch', {
    insight: shared,
    subscribed_users: [1],
    threshold: { configuration: { type: 'absolute', bounds: { upper: 1 } } },
})
