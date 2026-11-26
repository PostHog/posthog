import { FEATURE_FLAGS } from 'lib/constants'

import type { LinkBreadcrumb } from '~/types'

import { analyticsParentBreadcrumb } from './analyticsParentBreadcrumb'

const FLAG_ON = { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }
const OLD_PARENT: LinkBreadcrumb = { key: 'Dashboards', name: 'Dashboards', path: '/dashboard', iconType: 'dashboard' }

describe('analyticsParentBreadcrumb', () => {
    test.each([
        [
            'the Analytics page that opened the item',
            { backUrl: '/analytics/mine', backName: 'Analytics' },
            FLAG_ON,
            { name: 'Analytics', path: '/analytics/mine', iconType: 'dashboard' },
        ],
        ['the Analytics list when opened from elsewhere', {}, FLAG_ON, { name: 'Analytics', path: '/analytics/all' }],
        [
            'the Analytics list over a link another page left',
            { backUrl: '/feature_flags/12', backName: 'my-flag' },
            FLAG_ON,
            { name: 'Analytics', path: '/analytics/all' },
        ],
        ['the old parent without the flag', {}, {}, OLD_PARENT],
        ['the old parent without the flag, even with an Analytics link', { backUrl: '/analytics/all' }, {}, OLD_PARENT],
    ])('names %s as the parent breadcrumb', (_, searchParams, featureFlags, expected) => {
        expect(analyticsParentBreadcrumb(searchParams, featureFlags, OLD_PARENT)).toEqual(
            expect.objectContaining(expected)
        )
    })
})
