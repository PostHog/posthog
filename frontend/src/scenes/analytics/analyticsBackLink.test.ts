import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { withBackLink } from './analyticsBackLink'

describe('withBackLink', () => {
    beforeEach(() => {
        initKeaTests()
    })

    test.each([
        [
            'an Analytics page names itself',
            '/project/1/analytics/all?type=notebook',
            '/notebooks/abc',
            {
                backUrl: '/analytics/all?type=notebook',
                backName: 'Analytics',
            },
        ],
        [
            'a hop keeps the link it was given',
            '/project/1/notebooks/new?backUrl=%2Fanalytics&backName=Analytics',
            '/notebooks/abc',
            {
                backUrl: '/analytics',
                backName: 'Analytics',
            },
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
})
