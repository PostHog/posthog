import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { canvasesListLogic } from './canvasesListLogic'

describe('canvasesListLogic', () => {
    let requests: URLSearchParams[]

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/canvases/': (req) => {
                    requests.push(new URL(req.request.url).searchParams)
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })
        initKeaTests()
    })

    it('round-trips search, order and page through the URL', async () => {
        router.actions.push('/canvases', { search: 'ops', order: '-created_at', page: '3' })
        const logic = canvasesListLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['setListParams', 'loadCanvasesSuccess'])
        expect(logic.values).toMatchObject({ search: 'ops', ordering: '-created_at', page: 3 })
        expect(requests[0].get('search')).toBe('ops')
        expect(requests[0].get('ordering')).toBe('-created_at')
        expect(requests[0].get('offset')).toBe('100')

        logic.actions.setOrdering('-updated_at')
        expect(router.values.searchParams).toEqual({ search: 'ops' })

        logic.actions.setPage(2)
        expect(router.values.searchParams).toEqual({ search: 'ops', page: 2 })

        router.actions.push('/canvases', { page: 'junk', order: 'name' })
        expect(logic.values).toMatchObject({ search: '', ordering: '-updated_at', page: 1 })

        logic.unmount()
    })
})
