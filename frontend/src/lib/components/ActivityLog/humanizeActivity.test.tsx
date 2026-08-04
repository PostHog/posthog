import { ActivityLogItem, Describer, humanize, userNameForLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

describe('humanizeActivity', () => {
    const makeLogItem = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
        activity: 'updated',
        created_at: '2026-06-04T00:00:00Z',
        scope: ActivityScope.FEATURE_FLAG,
        detail: { merge: null, trigger: null, changes: null, name: 'my-flag' },
        ...overrides,
    })

    describe('userNameForLogItem', () => {
        it.each([
            [
                'uses the full name when set',
                { user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' } },
                'Ada Lovelace',
            ],
            [
                'falls back to email when the name is blank',
                { user: { first_name: '', last_name: '', email: 'ada@posthog.com' } },
                'ada@posthog.com',
            ],
            [
                'falls back to the placeholder when name and email are both blank',
                { user: { first_name: '', last_name: '', email: '' } },
                'A user',
            ],
            ['falls back to the placeholder when there is no user', {}, 'A user'],
            ['renders system activity as PostHog', { is_system: true }, 'PostHog'],
            [
                'falls back to email for impersonated actors with a blank name',
                { was_impersonated: true, user: { first_name: '', last_name: '', email: 'ada@posthog.com' } },
                'PostHog Support (as ada@posthog.com)',
            ],
        ])('%s', (_name, overrides: Partial<ActivityLogItem>, expected: string) => {
            expect(userNameForLogItem(makeLogItem(overrides))).toEqual(expected)
        })
    })

    describe('humanize', () => {
        it('skips a row whose describer throws instead of dropping the whole list', () => {
            const throwingItem = makeLogItem({ id: 'bad-row' })
            const okItem = makeLogItem({ id: 'good-row' })

            const describer: Describer = (logItem) => {
                if (logItem.id === 'bad-row') {
                    throw new TypeError("Cannot read properties of undefined (reading 'after')")
                }
                return { description: 'a fine description' }
            }

            const result = humanize([throwingItem, okItem], () => describer)

            expect(result).toHaveLength(1)
            expect(result[0].id).toEqual('good-row')
        })
    })
})
