import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { analyticsBackLink, analyticsParentBreadcrumb, withBackLink } from './analyticsBackLink'

const FLAG_ON = { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true }

describe('analyticsBackLink', () => {
    test.each([
        [
            'an Analytics list',
            { backUrl: '/analytics/all?type=notebook', backName: 'Analytics' },
            FLAG_ON,
            '/analytics/all?type=notebook',
        ],
        ['a project-prefixed Analytics page', { backUrl: '/project/1/analytics' }, FLAG_ON, '/project/1/analytics'],
        ["a flag's usage dashboard link", { backUrl: '/feature_flags/12', backName: 'my-flag' }, FLAG_ON, null],
        ['an external address', { backUrl: 'https://example.com/analytics' }, FLAG_ON, null],
        ['a protocol-relative address', { backUrl: '//example.com/analytics' }, FLAG_ON, null],
        ['an Analytics link for someone without the flag', { backUrl: '/analytics/all' }, {}, null],
        ['no link at all', {}, FLAG_ON, null],
    ])('trusts %s: %s', (_, searchParams, featureFlags, expected) => {
        expect(analyticsBackLink(searchParams, featureFlags)?.url ?? null).toBe(expected)
    })

    test.each([
        [
            'the Analytics page that opened the item',
            { backUrl: '/analytics/mine', backName: 'Analytics' },
            FLAG_ON,
            { name: 'Analytics', path: '/analytics/mine' },
        ],
        ['the Analytics list when opened from elsewhere', {}, FLAG_ON, { name: 'Analytics', path: '/analytics/all' }],
        [
            'the Analytics list over a link another page left',
            { backUrl: '/feature_flags/12', backName: 'my-flag' },
            FLAG_ON,
            { name: 'Analytics', path: '/analytics/all' },
        ],
        ['nothing without the flag', {}, {}, null],
        ['nothing without the flag, even with an Analytics link', { backUrl: '/analytics/all' }, {}, null],
    ])('names %s as the parent breadcrumb', (_, searchParams, featureFlags, expected) => {
        expect(analyticsParentBreadcrumb(searchParams, featureFlags)).toEqual(
            expected ? expect.objectContaining(expected) : null
        )
    })
})

describe('withBackLink', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], FLAG_ON)
    })

    test.each([
        [
            'an Analytics page names itself',
            '/project/1/analytics/all?type=notebook',
            '/notebooks/abc',
            { backUrl: '/analytics/all?type=notebook', backName: 'Analytics' },
        ],
        [
            'a hop keeps the Analytics link it was given',
            '/project/1/notebooks/new?backUrl=%2Fanalytics&backName=Analytics',
            '/notebooks/abc',
            { backUrl: '/analytics', backName: 'Analytics' },
        ],
        [
            'a hop drops a link another page left',
            '/project/1/dashboard/12?backUrl=%2Ffeature_flags%2F12&backName=my-flag',
            '/notebooks/abc',
            null,
        ],
        ['any other page leaves the URL alone', '/project/1/dashboard/12', '/notebooks/abc', null],
    ])('%s', (_, from, to, expected) => {
        router.actions.push(from)
        const result = withBackLink(to)
        if (!expected) {
            expect(result).toBe(to)
            return
        }
        const url = new URL(result, 'http://localhost')
        expect(url.pathname).toBe(to)
        expect(url.searchParams.get('backUrl')).toBe(expected.backUrl)
        expect(url.searchParams.get('backName')).toBe(expected.backName)
    })

    it('leaves the URL alone for someone without the flag, even on an Analytics page', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TODAY_RAIL_NAV], {})
        router.actions.push('/project/1/analytics/all')
        expect(withBackLink('/notebooks/abc')).toBe('/notebooks/abc')
    })
})
