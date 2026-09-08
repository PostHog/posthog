import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { RUNS_PAGE_SIZE, modelsRunsLogic } from './modelsRunsLogic'

describe('modelsRunsLogic', () => {
    let logic: ReturnType<typeof modelsRunsLogic.build>
    let requestedParams: URLSearchParams[]

    const mount = async (path: string): Promise<void> => {
        router.actions.push(path)
        logic = modelsRunsLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        requestedParams = []
        useMocks({
            get: {
                '/api/projects/:team_id/data_modeling_jobs/': ({ request }) => {
                    requestedParams.push(new URL(request.url).searchParams)
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
                '/api/environments/:team_id/data_modeling_nodes/': { count: 0, results: [] },
                '/api/environments/:team_id/warehouse_saved_queries/': { count: 0, results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('reads the status filter from the URL and sends it to the API', async () => {
        await mount('/models?tab=runs&status=Failed')

        expect(logic.values.statusFilter).toEqual('Failed')
        expect(requestedParams.at(-1)?.get('status')).toEqual('Failed')
    })

    it('ignores an unknown status in the URL', async () => {
        await mount('/models?tab=runs&status=Exploded')

        expect(logic.values.statusFilter).toBeNull()
        expect(requestedParams.at(-1)?.has('status')).toBe(false)
    })

    it('changing the filter resets to the first page and updates the URL', async () => {
        await mount('/models?tab=runs')
        logic.actions.setPage(3)
        await expectLogic(logic).toFinishAllListeners()
        expect(requestedParams.at(-1)?.get('offset')).toEqual(String(2 * RUNS_PAGE_SIZE))

        logic.actions.setStatusFilter('Completed')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.page).toEqual(1)
        expect(requestedParams.at(-1)?.get('offset')).toEqual('0')
        expect(requestedParams.at(-1)?.get('status')).toEqual('Completed')
        expect(router.values.searchParams).toEqual({ tab: 'runs', status: 'Completed' })
    })
})
