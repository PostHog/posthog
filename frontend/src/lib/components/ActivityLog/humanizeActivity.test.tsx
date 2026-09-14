import { render } from '@testing-library/react'

import { ActivityLogItem, ActivityLogUserName, userNameForLogItem } from 'lib/components/ActivityLog/humanizeActivity'

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

    describe('ActivityLogUserName', () => {
        // Base UI marks the element it merges the tooltip trigger onto. Opening the popup is not
        // reliable in jsdom because of the hover delay, so assert on the trigger instead.
        const renderName = (overrides: Partial<ActivityLogItem>): HTMLElement => {
            const { container } = render(<ActivityLogUserName logItem={makeLogItem(overrides)} />)
            const element = container.querySelector('strong')
            if (!element) {
                throw new Error('ActivityLogUserName rendered no name element')
            }
            return element
        }

        it.each([
            [
                'offers the email when the name does not already show it',
                { user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' } },
                true,
            ],
            [
                'stays plain when the visible name is already the email',
                { user: { first_name: '', last_name: '', email: 'ada@posthog.com' } },
                false,
            ],
            ['stays plain when the actor is the system', { is_system: true }, false],
            [
                'stays plain when a staff member was impersonating the actor',
                {
                    was_impersonated: true,
                    user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@posthog.com' },
                },
                false,
            ],
            ['stays plain when there is no user', {}, false],
        ])('%s', (_name, overrides: Partial<ActivityLogItem>, expectTooltip: boolean) => {
            const element = renderName(overrides)
            expect(element.hasAttribute('data-base-ui-tooltip-trigger')).toBe(expectTooltip)
            // The only visual cue that the name is hoverable.
            expect(element.classList.contains('cursor-help')).toBe(expectTooltip)
            // Dropping this on either branch sends every actor name into session replay.
            expect(element.classList.contains('ph-no-capture')).toBe(true)
        })
    })
})
