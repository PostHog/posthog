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
        const [page, sidebar] = await Promise.all([fetchViewItems('1', ''), fetchViewItems('1', '')])
        expect(requests).toBe(5)
        expect(page.truncated).toBe(true)
        expect(sidebar).toEqual(page)
        await fetchViewItems('1', '')
        expect(requests).toBe(8)
    })

    it('includes recent dashboards from later pages', async () => {
        let releaseSpaces!: () => void
        const spacesReady = new Promise<void>((resolve) => {
            releaseSpaces = resolve
        })
        let firstPage!: () => void
        const firstPageReady = new Promise<void>((resolve) => {
            firstPage = resolve
        })
        let releaseLaterPage!: () => void
        const laterPageReady = new Promise<void>((resolve) => {
            releaseLaterPage = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/task_channels/': async () => {
                    await spacesReady
                    return []
                },
                '/api/projects/:team_id/dashboards/': async ({ request }) => {
                    const offset = new URL(request.url).searchParams.get('offset')
                    if (offset !== '0') {
                        await laterPageReady
                    }
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
        const progress: string[][] = []
        const pending = fetchViewItems('1', '', (page) => {
            progress.push(page.items.map((item) => item.id))
            firstPage()
        })
        await firstPageReady
        expect(progress[0]).toEqual(['1'])
        const sidebarProgress = jest.fn()
        const sidebar = fetchViewItems('1', '', sidebarProgress)
        expect(sidebarProgress.mock.calls[0][0].items.map((item: { id: string }) => item.id)).toEqual(['1'])
        releaseLaterPage()
        releaseSpaces()
        const [page, sidebarPage] = await Promise.all([pending, sidebar])
        expect(page.failedTypes).toEqual([])
        expect(page.items.map((item) => item.id)).toEqual(['2', '1'])
        expect(sidebarPage).toEqual(page)
    })

    it.each([
        ['2', ''],
        ['1', 'Revenue'],
    ])('keeps project %s and search %s separate', async (projectId, search) => {
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': { results: [], next: null },
                '/api/projects/:team_id/notebooks/': { results: [], next: null },
                '/api/projects/:team_id/task_channels/': [],
                '/api/projects/:team_id/dashboards/': ({ request, params }) => ({
                    results: [
                        {
                            id: 1,
                            name: `${params.team_id}:${new URL(request.url).searchParams.get('search') ?? ''}`,
                            created_at: '2026-01-01',
                        },
                    ],
                    next: null,
                }),
            },
        })
        const [first, second] = await Promise.all([fetchViewItems('1', ''), fetchViewItems(projectId, search)])
        expect(first.items[0].name).toBe('1:')
        expect(second.items[0].name).toBe(`${projectId}:${search}`)
    })
})
