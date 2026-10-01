import { useMocks } from '~/mocks/jest'

import { fetchViewItems } from './fetchViewItems'

describe('fetchViewItems', () => {
    it('bounds pagination and marks an incomplete list', async () => {
        let requests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/dashboards/': () => {
                    requests += 1
                    return {
                        results: [{ id: requests, name: 'Dashboard', created_at: '2026-01-01' }],
                        next: requests < 8 ? `?offset=${requests}` : null,
                    }
                },
            },
        })
        const page = await fetchViewItems('1', '')
        expect(requests).toBe(5)
        expect(page.truncated).toBe(true)
    })

    it('includes recent dashboards from later pages', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/dashboards/': ({ request }) => {
                    const offset = new URL(request.url).searchParams.get('offset')
                    return offset === '0'
                        ? {
                              results: [{ id: 1, name: 'A', created_at: '2026-01-01', last_viewed_at: '2026-01-01' }],
                              next: '?offset=1',
                          }
                        : {
                              results: [{ id: 2, name: 'Z', created_at: '2026-01-01', last_viewed_at: '2026-01-02' }],
                              next: null,
                          }
                },
            },
        })
        const page = await fetchViewItems('1', '')
        expect(page.failedTypes).toEqual([])
        expect(page.items.map((item) => item.id)).toEqual(['2', '1'])
    })
})
