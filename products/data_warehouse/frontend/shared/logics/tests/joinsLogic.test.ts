import { expectLogic } from 'kea-test-utils'

import api, { ApiError, PaginatedResponse } from 'lib/api'

import { initKeaTests } from '~/test/init'
import { DataWarehouseViewLink } from '~/types'

import { joinsLogic } from '../joinsLogic'

// Stub the default `api` export but keep the real ApiError class so the fixtures and the
// `shouldReportApiFailure` gate reference the same constructor.
jest.mock('lib/api', () => {
    const actual = jest.requireActual('lib/api')
    return {
        __esModule: true,
        ...actual,
        default: {
            dataWarehouseViewLinks: {
                list: jest.fn(),
            },
        },
    }
})

const join = { id: 'join-1', source_table_name: 'events', field_name: 'stripe' } as DataWarehouseViewLink

const responseWithJoin: PaginatedResponse<DataWarehouseViewLink> = {
    results: [join],
    count: 1,
    next: null,
    previous: null,
} as PaginatedResponse<DataWarehouseViewLink>

describe('joinsLogic', () => {
    let logic: ReturnType<typeof joinsLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = joinsLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('keeps an empty state on a feature-gated 403 without surfacing loader failure', async () => {
        jest.spyOn(api.dataWarehouseViewLinks, 'list').mockRejectedValue(new ApiError('forbidden', 403))

        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadJoins', 'loadJoinsSuccess'])
            .toNotHaveDispatchedActions(['loadJoinsFailure'])
            .toMatchValues({ joins: [], joinsLoading: false })
    })

    it('still surfaces a genuine backend failure so it reaches error tracking', async () => {
        jest.spyOn(api.dataWarehouseViewLinks, 'list').mockRejectedValue(new ApiError('boom', 500))

        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadJoins', 'loadJoinsFailure']).toMatchValues({ joins: [] })
    })

    it('loads joins from the view links endpoint', async () => {
        jest.spyOn(api.dataWarehouseViewLinks, 'list').mockResolvedValue(responseWithJoin)

        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadJoins', 'loadJoinsSuccess'])
            .toMatchValues({ joins: [join], joinsLoading: false })
    })
})
