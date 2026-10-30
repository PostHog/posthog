import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    AnalyticsFeedQuery,
    AnalyticsSourceState,
    EMPTY_ANALYTICS_FEED_QUERY,
    mergeAnalyticsSources,
} from './analyticsFeed'
import { analyticsFeedLogic, resetAnalyticsFeedSnapshot, selectAnalyticsFeed } from './analyticsFeedLogic'
import { fileSystemEntryToAnalytics } from './analyticsUtils'

const ALL: AnalyticsFeedQuery = EMPTY_ANALYTICS_FEED_QUERY

const at = (day: number): string => `2026-09-${String(day).padStart(2, '0')}T00:00:00Z`
const ADA = { id: 1, uuid: 'u-ada', first_name: 'Ada', last_name: '', email: 'ada@example.com' }
const GRACE = { id: 2, uuid: 'u-grace', first_name: 'Grace', last_name: '', email: 'grace@example.com' }
const USERS = [ADA, GRACE]

const entry = (
    type: string,
    ref: string,
    path: string,
    createdAt: string,
    createdBy: typeof ADA
): Record<string, unknown> => ({
    id: `fs-${ref}`,
    type,
    ref,
    path,
    href: `/x/${ref}`,
    created_at: createdAt,
    last_viewed_at: null,
    meta: { created_by: createdBy.id },
})

describe('analyticsFeedLogic', () => {
    let requests: string[]
    let searches: (string | null)[]

    beforeEach(() => {
        resetAnalyticsFeedSnapshot()
        requests = []
        searches = []
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/file_system/unfiled/': () => {
                    requests.push('unfiled')
                    return { count: 0 }
                },
                '/api/projects/:team_id/file_system/': ({ request }) => {
                    const params = new URL(request.url).searchParams
                    const type = params.get('type') ?? params.get('type__startswith') ?? ''
                    const offset = params.get('offset') ?? '0'
                    requests.push(`${type}:${offset}:${params.get('order_by')}`)
                    searches.push(params.get('search'))
                    if (type === 'canvas') {
                        return { results: [entry('canvas', 'c7', 'Growth/C', at(7), GRACE)], users: USERS, next: null }
                    }
                    if (type === 'notebook') {
                        return {
                            results: [
                                entry('notebook', 'n9', 'Unfiled/Notebooks/N', at(9), ADA),
                                entry('notebook', 'n1', 'Growth/N', at(1), ADA),
                            ],
                            users: USERS,
                            next: null,
                        }
                    }
                    if (type === 'insight') {
                        return {
                            results: [entry('insight/trends', 'i5', 'Growth/I', at(5), ADA)],
                            users: USERS,
                            next: null,
                        }
                    }
                    return offset === '0'
                        ? {
                              results: [
                                  entry('dashboard', '10', 'Growth/D', at(10), ADA),
                                  entry('dashboard', '8', 'Unfiled/Dashboards/D', at(8), GRACE),
                              ],
                              users: USERS,
                              next: '?offset=2',
                          }
                        : {
                              results: [entry('dashboard', '3', 'Growth/D', at(3), ADA)],
                              users: USERS,
                              next: null,
                          }
                },
            },
        })
        initKeaTests()
    })

    const feed = (logic: ReturnType<typeof analyticsFeedLogic.build>, query: AnalyticsFeedQuery = ALL): string[] =>
        selectAnalyticsFeed(logic.values.sources, teamLogic.values.currentTeamId, query).items.map(
            (item) => `${item.type}:${item.id}`
        )

    it('shows only rows whose order is final, and loads more from the type that holds them back', async () => {
        const logic = analyticsFeedLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.refreshFeed(ALL)).toFinishAllListeners()
        expect(feed(logic)).toEqual(['dashboard:10', 'notebook:n9', 'dashboard:8'])

        await expectLogic(logic, () => logic.actions.ensureFeed(ALL, 100)).toFinishAllListeners()
        expect(feed(logic)).toEqual([
            'dashboard:10',
            'notebook:n9',
            'dashboard:8',
            'canvas:c7',
            'insight:i5',
            'dashboard:3',
            'notebook:n1',
        ])
        // The unfiled sweep runs once, before any source is read, so pre-sync objects get their rows.
        expect(requests[0]).toBe('unfiled')
        expect(requests.filter((request) => request === 'unfiled')).toHaveLength(1)
        expect(requests.filter((request) => request !== 'unfiled').sort()).toEqual([
            'canvas:0:-created_at',
            'dashboard:0:-created_at',
            'dashboard:2:-created_at',
            'insight:0:-created_at',
            'notebook:0:-created_at',
        ])
        const result = selectAnalyticsFeed(logic.values.sources, teamLogic.values.currentTeamId, ALL)
        expect(result.hasMore).toBe(false)
        expect(result.items.map((item) => item.spaceName)).toEqual([
            'Growth',
            null,
            null,
            'Growth',
            'Growth',
            'Growth',
            'Growth',
        ])
    })

    it.each([
        ['another person, on the client alone', false, null],
        ['the current person, on the server too', true, 'user:me'],
    ])('narrows rows to %s', async (_, createdByMe, search) => {
        const logic = analyticsFeedLogic()
        logic.mount()
        const byAda: AnalyticsFeedQuery = { ...ALL, createdBy: ['u-ada'], createdByMe }

        await expectLogic(logic, () => logic.actions.ensureFeed(byAda, 100)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.ensureFeed(byAda, 100)).toFinishAllListeners()

        expect(feed(logic, byAda)).toEqual(['dashboard:10', 'notebook:n9', 'insight:i5', 'dashboard:3', 'notebook:n1'])
        expect(new Set(searches)).toEqual(new Set([search]))
    })

    it('keeps the loaded list after a remount, so a revisit shows rows at once', async () => {
        const first = analyticsFeedLogic()
        first.mount()
        await expectLogic(first, () => first.actions.refreshFeed(ALL)).toFinishAllListeners()
        first.unmount()

        const second = analyticsFeedLogic()
        second.mount()

        expect(feed(second)).toEqual(['dashboard:10', 'notebook:n9', 'dashboard:8'])
    })
})

describe('mergeAnalyticsSources view order', () => {
    test.each(['-last_viewed_at', 'last_viewed_at'] as const)(
        'merges %s across types with unviewed rows last',
        (orderBy) => {
            const source = (type: 'dashboard' | 'notebook', days: (number | null)[]): AnalyticsSourceState => ({
                projectId: '1',
                query: { ...ALL, orderBy },
                type,
                items: days.map((day, index) => ({
                    ...fileSystemEntryToAnalytics({
                        id: `fs-${type}-${index}`,
                        type,
                        ref: `${type}-${index}`,
                        path: `${type}/${index}`,
                        created_at: at(30 - index),
                    })!,
                    timestamp: day === null ? null : at(day),
                })),
                offset: days.length,
                hasMore: false,
                initialized: true,
                refreshing: false,
                loading: false,
                failed: false,
                generation: 0,
            })
            const dashboards = orderBy === '-last_viewed_at' ? [5, 2, null] : [2, 5, null]
            const { items } = mergeAnalyticsSources([source('dashboard', dashboards), source('notebook', [3, null])])
            const expected = orderBy === '-last_viewed_at' ? [5, 3, 2, null, null] : [2, 3, 5, null, null]
            expect(items.map((item) => item.timestamp)).toEqual(expected.map((day) => (day === null ? null : at(day))))
            expect(items.slice(-2).map((item) => item.type)).toEqual(['notebook', 'dashboard'])
        }
    )
})
