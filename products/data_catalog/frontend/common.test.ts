import { sqlNameFromDisplayName, validateMetricName } from './common'

describe('sqlNameFromDisplayName', () => {
    it.each([
        ['Monthly active users', 'monthly_active_users'],
        ['  Revenue (USD) / day  ', 'revenue_usd_day'],
        ['30-day retention', 'metric_30_day_retention'],
        ['Café visits', 'cafe_visits'],
        ['weekly_signups', 'weekly_signups'],
        ['月活跃用户', ''],
    ])('derives a valid SQL name from %p', (displayName, expected) => {
        const sqlName = sqlNameFromDisplayName(displayName)
        expect(sqlName).toEqual(expected)
        if (sqlName) {
            expect(validateMetricName(sqlName)).toBeUndefined()
        }
    })
})
