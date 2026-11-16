import { sqlNameAfterDisplayNameChange, sqlNameFromDisplayName, validateMetricName } from './common'

describe('metric SQL names', () => {
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

    it.each([
        [
            'follows the display name while it was derived from it',
            'Weekly signups',
            'weekly_signups',
            'weekly_signups_v2',
        ],
        ['starts following from an empty form', '', '', 'weekly_signups_v2'],
        ['stays fixed once the user edited it', 'Weekly signups', 'signups_custom', 'signups_custom'],
    ])('the SQL name %s', (_case, displayName, sqlName, expected) => {
        expect(sqlNameAfterDisplayNameChange(displayName, sqlName, 'Weekly signups v2')).toEqual(expected)
    })
})
