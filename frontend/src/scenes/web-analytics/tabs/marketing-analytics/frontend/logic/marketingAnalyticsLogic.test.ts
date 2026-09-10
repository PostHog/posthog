import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { ExternalDataSchemaStatus, ExternalDataSource } from '~/types'

import { ExternalTable, getSourceStatus, marketingAnalyticsLogic } from './marketingAnalyticsLogic'

// Kea builds this from the reducer's path and name. It is pinned in the logic, so a rename cannot
// silently point the reducer at a different key and abandon what someone already saved.
const STORAGE_KEY = `${MOCK_TEAM_ID}__.scenes.webAnalytics.marketingAnalyticsLogic.integrationFilter`

describe('marketingAnalyticsLogic', () => {
    let logic: ReturnType<typeof marketingAnalyticsLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
    })

    afterEach(() => {
        if (logic?.cache.mounted) {
            logic.unmount()
        }
        localStorage.clear()
    })

    it('keeps the selection and drops an unknown key from a filter saved by an older build', async () => {
        localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ integrationSourceIds: ['source-1'], includeNonIntegrated: true })
        )

        logic = marketingAnalyticsLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({
            integrationFilter: { integrationSourceIds: ['source-1'] },
        })
    })

    describe('getSourceStatus', () => {
        const source = { id: 'source-1', name: 'GoogleAds', type: 'native' }

        const nativeSourceWithFailedSchema = (latestError: string | null): ExternalDataSource =>
            ({
                id: 'source-1',
                source_type: 'GoogleAds',
                schemas: [
                    { id: 'schema-1', name: 'campaign', should_sync: true, status: ExternalDataSchemaStatus.Completed },
                    {
                        id: 'schema-2',
                        name: 'campaign_overview_stats',
                        should_sync: true,
                        status: ExternalDataSchemaStatus.Failed,
                        latest_error: latestError,
                    },
                ],
            }) as unknown as ExternalDataSource

        it('reports the sync error the backend wrote for a failed native source', () => {
            expect(
                getSourceStatus(source, [nativeSourceWithFailedSchema('The credential is unavailable.')], [])
            ).toEqual({ status: ExternalDataSchemaStatus.Failed, message: 'The credential is unavailable.' })
        })

        it('falls back to a generic message when a failed native source has no sync error', () => {
            expect(getSourceStatus(source, [nativeSourceWithFailedSchema(null)], [])).toEqual({
                status: ExternalDataSchemaStatus.Failed,
                message: 'One or more required tables failed to sync.',
            })
        })

        it('reports the sync error the backend wrote for a failed warehouse table', () => {
            const table = {
                source_map_id: 'source-1',
                source_map: { campaign_name: 'name' },
                schema_status: ExternalDataSchemaStatus.Failed,
                latest_error: 'The credential is unavailable.',
            } as unknown as ExternalTable

            expect(getSourceStatus(source, [], [table])).toEqual({
                status: ExternalDataSchemaStatus.Failed,
                message: 'The credential is unavailable.',
            })
        })
    })
})
