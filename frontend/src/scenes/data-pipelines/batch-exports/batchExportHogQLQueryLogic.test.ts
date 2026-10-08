import { expectLogic } from 'kea-test-utils'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration } from '~/types'

import { BatchExportConfigFormLogicProps, batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import { batchExportHogQLEditorTabId, batchExportHogQLQueryLogic } from './batchExportHogQLQueryLogic'

const EXPORT_ID = 'test-hogql-export-id'
const PROPS: BatchExportConfigFormLogicProps = { id: EXPORT_ID, service: null }

function hogqlExport(): BatchExportConfiguration {
    return {
        id: EXPORT_ID,
        team_id: 997,
        name: 'HogQL export',
        destination: {
            type: 'AwsS3',
            integration: 31,
            config: {
                bucket_name: 'test-bucket',
                region: 'us-east-1',
                prefix: 'exports/',
                exclude_events: [],
                include_events: [],
                compression: 'zstd',
                encryption: null,
                kms_key_id: null,
                file_format: 'Parquet',
                max_file_size_mb: null,
            },
        } as BatchExportConfiguration['destination'],
        interval: 'hour',
        timezone: null,
        offset_day: null,
        offset_hour: null,
        created_at: '2024-01-01T00:00:00Z',
        start_at: null,
        end_at: null,
        paused: false,
        model: 'hogql',
        hogql_query: 'SELECT event FROM events WHERE timestamp >= {data_interval_start}',
        filters: [],
    }
}

describe('batchExportHogQLQueryLogic', () => {
    let logic: ReturnType<typeof batchExportHogQLQueryLogic.build>
    let formLogic: ReturnType<typeof batchExportConfigFormLogic.build>

    const editorLogic = (props: BatchExportConfigFormLogicProps = PROPS): ReturnType<typeof sqlEditorLogic.build> =>
        sqlEditorLogic({ tabId: batchExportHogQLEditorTabId(props), mode: SQLEditorMode.Embedded })

    async function initLogic(props: BatchExportConfigFormLogicProps = PROPS): Promise<void> {
        formLogic = batchExportConfigFormLogic(props)
        formLogic.mount()
        await expectLogic(formLogic).toFinishAllListeners()
        logic = batchExportHogQLQueryLogic(props)
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/environments/:team_id/batch_exports/${EXPORT_ID}`]: hogqlExport(),
                '/api/environments/:team_id/batch_exports/test': { steps: [] },
                '/api/projects/:team_id/integrations/': { count: 0, results: [] },
            },
        })
        initKeaTests()
    })

    // The form saves `hogql_query`, so it must match what the editor shows. A form reset, such as "Clear changes",
    // must also reach the editor, or the editor keeps text that the form no longer holds.
    it('copies editor changes into the form', async () => {
        await initLogic()

        editorLogic().actions.setQueryInput('SELECT 2')
        await expectLogic(logic).toFinishAllListeners()

        expect(formLogic.values.configuration.hogql_query).toEqual('SELECT 2')
    })

    it('restores the editor when the form resets', async () => {
        await initLogic()
        editorLogic().actions.setQueryInput('SELECT 2')
        await expectLogic(logic).toFinishAllListeners()

        formLogic.actions.resetConfiguration(formLogic.values.savedConfiguration)
        await expectLogic(logic).toFinishAllListeners()

        expect(editorLogic().values.queryInput).toEqual(hogqlExport().hogql_query)
    })

    it('gives the editor preview values that follow the schedule', async () => {
        await initLogic()
        const hourlyPlaceholders = editorLogic().values.placeholders
        expect(hourlyPlaceholders).toEqual(logic.values.placeholders)

        formLogic.actions.setConfigurationValue('interval', 'day')
        await expectLogic(logic).toFinishAllListeners()

        expect(editorLogic().values.placeholders).toEqual(logic.values.placeholders)
        expect(editorLogic().values.placeholders).not.toEqual(hourlyPlaceholders)
    })

    it('starts a new export with the default query in both the editor and the form', async () => {
        const newExportProps: BatchExportConfigFormLogicProps = { id: null, service: 'AwsS3' }
        await initLogic(newExportProps)

        const queryInput = editorLogic(newExportProps).values.queryInput
        expect(queryInput).toContain('{data_interval_start}')
        expect(formLogic.values.configuration.hogql_query).toEqual(queryInput)
    })
})
