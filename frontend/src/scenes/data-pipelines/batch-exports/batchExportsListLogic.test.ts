import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { BatchExportApi } from 'products/batch_exports/frontend/generated/api.schemas'

import { batchExportsListLogic } from './batchExportsListLogic'

const makeBatchExport = (
    id: string,
    name: string,
    destination: BatchExportApi['destination'],
    paused: boolean
): BatchExportApi => ({
    id,
    team_id: 997,
    name,
    destination,
    interval: 'hour',
    paused,
    created_at: '2024-01-01T00:00:00Z',
    last_updated_at: '2024-01-01T00:00:00Z',
    latest_runs: [],
    schema: null,
})

const ACTIVE_EXPORT = makeBatchExport(
    'active',
    'Hourly bucket',
    { type: 'AwsS3', config: { type: 'AwsS3', bucket_name: 'exports', region: 'us-east-1', prefix: 'events/' } },
    false
)
const PAUSED_EXPORT = makeBatchExport(
    'paused',
    'Nightly warehouse',
    { type: 'Snowflake', config: { type: 'Snowflake', database: 'analytics', warehouse: 'compute', schema: 'public' } },
    true
)

describe('batchExportsListLogic', () => {
    let logic: ReturnType<typeof batchExportsListLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/batch_exports/': {
                    count: 2,
                    next: null,
                    previous: null,
                    // Paused first, so the sort by status is what puts the active export on top.
                    results: [PAUSED_EXPORT, ACTIVE_EXPORT],
                },
            },
        })
        initKeaTests()
        await expectLogic(teamLogic).toFinishAllListeners()
        logic = batchExportsListLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('hides paused exports until "Show paused" is on, and counts them as hidden', async () => {
        await expectLogic(logic).toMatchValues({
            filteredBatchExports: [ACTIVE_EXPORT],
            hiddenBatchExports: [PAUSED_EXPORT],
        })

        logic.actions.setFilters({ showPaused: true })

        await expectLogic(logic).toMatchValues({
            filteredBatchExports: [ACTIVE_EXPORT, PAUSED_EXPORT],
            hiddenBatchExports: [],
        })
    })

    it.each([
        ['nightly', [PAUSED_EXPORT]],
        ['snowflake', [PAUSED_EXPORT]],
        ['bucket', [ACTIVE_EXPORT]],
    ])('matches the search "%s" against the name and the destination service', async (search, expected) => {
        logic.actions.setFilters({ showPaused: true, search })

        await expectLogic(logic).toMatchValues({ filteredBatchExports: expected })
    })
})
