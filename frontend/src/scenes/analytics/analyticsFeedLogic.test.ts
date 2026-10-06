import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { AnalyticsFeedQuery, EMPTY_ANALYTICS_FEED_QUERY } from './analyticsFeed'
import { analyticsFeedLogic, resetAnalyticsFeedSnapshot, selectAnalyticsFeed } from './analyticsFeedLogic'

const ALL: AnalyticsFeedQuery = EMPTY_ANALYTICS_FEED_QUERY

const at = (day: number): string => `2026-09-${String(day).padStart(2, '0')}T00:00:00Z`
const ADA = { id: 1, uuid: 'u-ada', first_name: 'Ada', last_name: '', email: 'ada@example.com' }
const GRACE = { id: 2, uuid: 'u-grace', first_name: 'Grace', last_name: '', email: 'grace@example.com' }

describe('analyticsFeedLogic', () => {
    let requests: Record<string, string[]>

    beforeEach(() => {
        resetAnalyticsFeedSnapshot()
        requests = { canvases: [], notebooks: [], dashboards: [], insights: [] }
        const record = (name: string, request: Request): URLSearchParams => {
            const params = new URL(request.url).searchParams
            requests[name].push(
                `${params.get('offset')}:${params.get('ordering') ?? params.get('order') ?? ''}:${params.get('created_by') ?? ''}`
            )
            return params
        }
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [{ id: 'space-1', name: 'growth' }],
                '/api/projects/:team_id/canvases/': ({ request }) => {
                    record('canvases', request)
                    return {
                        results: [
                            {
                                id: 'c7',
                                name: 'C',
                                kind: 'freeform',
                                channel: 'space-1',
                                updated_at: at(7),
                                created_by: GRACE,
                            },
                        ],
                        next: null,
                    }
                },
                '/api/projects/:team_id/notebooks/': ({ request }) => {
                    record('notebooks', request)
                    return {
                        results: [
                            { short_id: 'n9', title: 'N', deleted: false, last_modified_at: at(9), created_by: ADA },
                            { short_id: 'n1', title: 'N', deleted: false, last_modified_at: at(1), created_by: ADA },
                        ],
                        next: null,
                    }
                },
                '/api/projects/:team_id/dashboards/': ({ request }) => {
                    const params = record('dashboards', request)
                    return params.get('offset') === '0'
                        ? {
                              results: [
                                  { id: 10, name: 'D', last_viewed_at: at(10), created_at: at(1), created_by: ADA },
                                  { id: 8, name: 'D', last_viewed_at: null, created_at: at(8), created_by: GRACE },
                              ],
                              next: '?offset=2',
                          }
                        : {
                              results: [
                                  { id: 3, name: 'D', last_viewed_at: at(3), created_at: at(1), created_by: ADA },
                              ],
                              next: null,
                          }
                },
                '/api/projects/:team_id/insights/': ({ request }) => {
                    record('insights', request)
                    return {
                        results: [{ short_id: 'i5', name: 'I', last_modified_at: at(5), created_by: ADA }],
                        next: null,
                    }
                },
            },
        })
        initKeaTests()
    })

    const feed = (logic: ReturnType<typeof analyticsFeedLogic.build>, query: AnalyticsFeedQuery = ALL): string[] =>
        selectAnalyticsFeed(
            logic.values.sources,
            logic.values.spaceNames,
            teamLogic.values.currentTeamId,
            query
        ).items.map((item) => `${item.type}:${item.id}`)

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
        expect(requests).toEqual({
            canvases: ['0:-updated_at:'],
            notebooks: ['0::'],
            dashboards: ['0:-last_viewed_at:', '2:-last_viewed_at:'],
            insights: ['0:-last_modified_at:'],
        })
        const result = selectAnalyticsFeed(
            logic.values.sources,
            logic.values.spaceNames,
            teamLogic.values.currentTeamId,
            ALL
        )
        expect(result.hasMore).toBe(false)
        expect(result.items.find((item) => item.type === 'canvas')?.spaceName).toBe('growth')
        expect(result.items.filter((item) => item.type === 'dashboard').map((item) => item.timestampLabel)).toEqual([
            'Viewed',
            'Created',
            'Viewed',
        ])
    })

    it('filters by creator on the server where the API can, and on the client where it cannot', async () => {
        const logic = analyticsFeedLogic()
        logic.mount()
        const byAda: AnalyticsFeedQuery = { ...ALL, createdBy: { uuid: 'u-ada', id: 1 } }

        await expectLogic(logic, () => logic.actions.ensureFeed(byAda, 100)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.ensureFeed(byAda, 100)).toFinishAllListeners()

        expect(feed(logic, byAda)).toEqual(['dashboard:10', 'notebook:n9', 'insight:i5', 'dashboard:3', 'notebook:n1'])
        expect(requests.notebooks).toEqual(['0::u-ada'])
        expect(requests.insights).toEqual(['0:-last_modified_at:[1]'])
        expect(requests.dashboards).toEqual(['0:-last_viewed_at:', '2:-last_viewed_at:'])
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
