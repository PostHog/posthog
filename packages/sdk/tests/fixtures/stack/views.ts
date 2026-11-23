import { alert, dashboard, trend } from '@posthog/sdk/define'

const signups = trend({ name: 'Signups', series: [{ event: 'signed_up' }], interval: 'week' })

export const growth = dashboard('growth', { name: 'Growth', tiles: [signups] })

export const signupDrop = alert('signup_drop', {
    insight: { $ref: { kind: 'insight', key: 'growth-signups' } },
    subscribed_users: [1],
    threshold: { configuration: { type: 'absolute', bounds: { lower: 10 } } },
})
