import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'

import { databaseTableListLogic } from './databaseTableListLogic'

jest.mock('~/queries/query')

describe('databaseTableListLogic', () => {
    let logic: ReturnType<typeof databaseTableListLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {},
            joins: [],
        })
    })

    afterEach(() => {
        logic?.unmount()
        window.history.replaceState({}, '', urls.sqlEditor())
        jest.clearAllMocks()
    })

    it('defers the initial database load on the sql editor when a connection hash is present', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
            [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
        })
        window.history.replaceState({}, '', `${urls.sqlEditor()}#c=conn-123`)

        logic = databaseTableListLogic()
        logic.mount()

        expect(logic.values.connectionId).toEqual('conn-123')
        expect(performQuery).not.toHaveBeenCalled()
    })

    it('loads immediately when there is no sql editor connection hash to wait for', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY], {
            [FEATURE_FLAGS.DWH_POSTGRES_DIRECT_QUERY]: true,
        })
        window.history.replaceState({}, '', urls.sqlEditor())

        logic = databaseTableListLogic()
        logic.mount()

        expect(performQuery).toHaveBeenCalledTimes(1)
    })
})
