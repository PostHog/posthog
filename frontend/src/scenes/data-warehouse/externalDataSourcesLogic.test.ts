import { expectLogic } from 'kea-test-utils'
import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { externalDataSourcesLogic } from './externalDataSourcesLogic'

jest.mock('lib/api')

describe('externalDataSourcesLogic', () => {
    let logic: ReturnType<typeof externalDataSourcesLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = externalDataSourcesLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads external data sources', async () => {
        const mockResponse = {
            results: [{ id: 'test-1', source_type: 'postgres', status: 'Running', schemas: [] }],
            count: 1,
            next: null,
            previous: null,
        }

        jest.spyOn(api.externalDataSources, 'list').mockResolvedValue(mockResponse as any)

        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadSources(null)
        })
            .toDispatchActions(['loadSources', 'loadSourcesSuccess'])
            .toMatchValues({
                dataWarehouseSources: mockResponse,
                dataWarehouseSourcesLoading: false,
            })

        expect(api.externalDataSources.list).toHaveBeenCalledWith({ signal: expect.any(AbortSignal) })
    })
})
