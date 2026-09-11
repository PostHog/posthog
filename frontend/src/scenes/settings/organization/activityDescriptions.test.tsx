import { render, within } from '@testing-library/react'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { organizationActivityDescriber } from './activityDescriptions'

describe('organizationActivityDescriber', () => {
    const makeInviteLogItem = (
        context: Record<string, any>,
        overrides: Partial<ActivityLogItem> = {}
    ): ActivityLogItem => ({
        user: { first_name: 'Grace', last_name: 'Hopper', email: 'grace@example.com' },
        activity: 'created',
        created_at: '2026-06-04T00:00:00Z',
        scope: ActivityScope.ORGANIZATION_INVITE,
        detail: {
            merge: null,
            trigger: null,
            changes: null,
            name: null,
            context: {
                organization_name: 'Analytics Inc',
                target_email: 'newcomer@example.com',
                level: 'member',
                inviter_user_name: 'Ada Lovelace',
                inviter_user_email: 'ada@example.com',
                ...context,
            },
        },
        ...overrides,
    })

    // Base UI marks the element it merges the tooltip trigger onto. Opening the popup is not
    // reliable in jsdom because of the hover delay, so assert on the trigger instead.
    const renderInviterName = (context: Record<string, any>, overrides?: Partial<ActivityLogItem>): HTMLElement => {
        const { description } = organizationActivityDescriber(makeInviteLogItem(context, overrides))
        const { container } = render(description as JSX.Element)
        return within(container).getByText('Ada Lovelace')
    }

    it.each([
        ['offers the inviter email on an ordinary invite row', {}, undefined, true],
        ['stays plain when the context carries no inviter email', { inviter_user_email: null }, undefined, false],
        [
            'stays plain when a staff member was impersonating the actor',
            {},
            { was_impersonated: true } as Partial<ActivityLogItem>,
            false,
        ],
        ['stays plain when the actor is the system', {}, { is_system: true } as Partial<ActivityLogItem>, false],
    ])('%s', (_name, context, overrides, expectTooltip) => {
        const element = renderInviterName(context, overrides)
        expect(element.hasAttribute('data-base-ui-tooltip-trigger')).toBe(expectTooltip)
        expect(element.classList.contains('ph-no-capture')).toBe(true)
    })
})
