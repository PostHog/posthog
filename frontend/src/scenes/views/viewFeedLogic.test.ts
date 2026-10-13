import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ViewFeedQuery } from './viewFeed'
import { resetViewFeedSnapshot, selectViewFeed, viewFeedLogic } from './viewFeedLogic'

const ALL: ViewFeedQuery = { type: 'all', search: '' }

const at = (day: number): string => `2026-09-${String(day).padStart(2, '0')}T00:00:00Z`

describe('viewFeedLogic', () => {
    let requests: Record<string, string[]>

    beforeEach(() => {
        resetViewFeedSnapshot()
        requests = { canvases: [], notebooks: [], dashboards: [] }
        const record = (name: string, request: Request): URLSearchParams => {
            const params = new URL(request.url).searchParams
            requests[name].push(`${params.get('offset')}:${params.get('ordering') ?? ''}`)
            return params
        }
        useMocks({
            get: {
                '/api/projects/:team_id/task_channels/': [{ id: 'space-1', name: 'growth' }],
                '/api/projects/:team_id/canvases/': ({ request }) => {
                    record('canvases', request)
                    return {
                        results: [{ id: 'c7', name: 'C', kind: 'freeform', channel: 'space-1', updated_at: at(7) }],
                        next: null,
                    }
                },
                '/api/projects/:team_id/notebooks/': ({ request }) => {
                    record('notebooks', request)
                    return {
                        results: [
                            { short_id: 'n9', title: 'N', deleted: false, last_modified_at: at(9) },
                            { short_id: 'n1', title: 'N', deleted: false, last_modified_at: at(1) },
                        ],
                        next: null,
                    }
                },
                '/api/projects/:team_id/dashboards/': ({ request }) => {
                    const params = record('dashboards', request)
                    return params.get('offset') === '0'
                        ? {
                              results: [
                                  { id: 10, name: 'D', last_viewed_at: at(10), created_at: at(1) },
                                  { id: 8, name: 'D', last_viewed_at: null, created_at: at(8) },
                              ],
                              next: '?offset=2',
                          }
                        : { results: [{ id: 3, name: 'D', last_viewed_at: at(3), created_at: at(1) }], next: null }
                },
            },
        })
        initKeaTests()
    })

    const feed = (logic: ReturnType<typeof viewFeedLogic.build>): string[] =>
        selectViewFeed(logic.values.sources, logic.values.spaceNames, teamLogic.values.currentTeamId, ALL).items.map(
            (item) => `${item.type}:${item.id}`
        )

    it('shows only rows whose order is final, and loads more from the type that holds them back', async () => {
        const logic = viewFeedLogic()
        logic.mount()

        await expectLogic(logic, () => logic.actions.refreshFeed(ALL)).toFinishAllListeners()
        expect(feed(logic)).toEqual(['dashboard:10', 'notebook:n9', 'dashboard:8'])

        await expectLogic(logic, () => logic.actions.ensureFeed(ALL, 100)).toFinishAllListeners()
        expect(feed(logic)).toEqual([
            'dashboard:10',
            'notebook:n9',
            'dashboard:8',
            'canvas:c7',
            'dashboard:3',
            'notebook:n1',
        ])
        expect(requests).toEqual({
            canvases: ['0:-updated_at'],
            notebooks: ['0:'],
            dashboards: ['0:-last_viewed_at', '2:-last_viewed_at'],
        })
        const result = selectViewFeed(
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

    it('keeps the loaded list after a remount, so a revisit shows rows at once', async () => {
        const first = viewFeedLogic()
        first.mount()
        await expectLogic(first, () => first.actions.refreshFeed(ALL)).toFinishAllListeners()
        first.unmount()

        const second = viewFeedLogic()
        second.mount()

        expect(feed(second)).toEqual(['dashboard:10', 'notebook:n9', 'dashboard:8'])
    })
})
