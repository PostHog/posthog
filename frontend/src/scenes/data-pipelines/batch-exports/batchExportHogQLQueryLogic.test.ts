import { expectLogic } from 'kea-test-utils'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BatchExportConfiguration } from '~/types'

import { BatchExportConfigFormLogicProps, batchExportConfigFormLogic } from './batchExportConfigFormLogic'
import {
    TimestampTimezoneChoice,
    batchExportHogQLEditorTabId,
    batchExportHogQLQueryLogic,
} from './batchExportHogQLQueryLogic'

const EXPORT_ID = 'test-hogql-export-id'
const PROPS: BatchExportConfigFormLogicProps = { id: EXPORT_ID, service: null }
const PROJECT_TIMEZONE = 'Europe/Berlin'

function hogqlExport(hogqlModifiers: HogQLQueryModifiers | null): BatchExportConfiguration {
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
        hogql_modifiers: hogqlModifiers,
        filters: [],
    }
}

describe('batchExportHogQLQueryLogic', () => {
    let logic: ReturnType<typeof batchExportHogQLQueryLogic.build>
    let formLogic: ReturnType<typeof batchExportConfigFormLogic.build>
    // The saved export's `hogql_modifiers`, which the mocked GET returns. Each test sets it through initLogic.
    let savedExportModifiers: HogQLQueryModifiers | null = null

    const editorLogic = (props: BatchExportConfigFormLogicProps = PROPS): ReturnType<typeof sqlEditorLogic.build> =>
        sqlEditorLogic({ tabId: batchExportHogQLEditorTabId(props), mode: SQLEditorMode.Embedded })

    async function initLogic(
        teamModifiers: HogQLQueryModifiers | undefined,
        exportModifiers: HogQLQueryModifiers | null,
        props: BatchExportConfigFormLogicProps = PROPS
    ): Promise<void> {
        savedExportModifiers = exportModifiers
        await expectLogic(teamLogic).toFinishAllListeners()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...teamLogic.values.currentTeam!,
            timezone: PROJECT_TIMEZONE,
            modifiers: teamModifiers,
        })
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
                [`/api/environments/:team_id/batch_exports/${EXPORT_ID}`]: () => [
                    200,
                    hogqlExport(savedExportModifiers),
                ],
                '/api/environments/:team_id/batch_exports/test': { steps: [] },
                '/api/projects/:team_id/integrations/': { count: 0, results: [] },
            },
        })
        initKeaTests()
    })

    // The backend resolves `convertToProjectTimezone` from the export's modifiers, then `team.modifiers`, then
    // `true`. The form label and the preview's placeholder timezone must follow the same order. If the logic skips
    // `team.modifiers`, a team that turned the modifier off through the API sees its project timezone in the form
    // while its exports run in UTC.
    test.each<
        [string, HogQLQueryModifiers | undefined, HogQLQueryModifiers | null, TimestampTimezoneChoice, boolean, string]
    >([
        ['the team leaves it unset', undefined, null, 'project_setting', true, PROJECT_TIMEZONE],
        ['the team turns it off', { convertToProjectTimezone: false }, null, 'project_setting', false, 'UTC'],
        [
            'the export turns it on over the team',
            { convertToProjectTimezone: false },
            { convertToProjectTimezone: true },
            'project_timezone',
            false,
            PROJECT_TIMEZONE,
        ],
        [
            'the export turns it off over the default',
            undefined,
            { convertToProjectTimezone: false },
            'utc',
            true,
            'UTC',
        ],
    ])(
        'resolves the query timezone when %s',
        async (_, teamModifiers, exportModifiers, choice, projectConverts, queryTimezone) => {
            await initLogic(teamModifiers, exportModifiers)

            await expectLogic(logic).toMatchValues({
                timestampTimezoneChoice: choice,
                projectConvertsToProjectTimezone: projectConverts,
                queryTimezone,
            })
            const { start, end } = logic.values.previewInterval
            expect(editorLogic().values.placeholders.map((placeholder) => placeholder.previewValue)).toEqual([
                start.tz(queryTimezone).format('YYYY-MM-DD HH:mm:ss'),
                end.tz(queryTimezone).format('YYYY-MM-DD HH:mm:ss'),
            ])
        }
    )

    // The form controls only `convertToProjectTimezone`. Other keys can come from the API, and the backend replaces
    // the whole `hogql_modifiers` object on save, so changing the choice must keep them. The editor must get the
    // same modifiers, or the preview runs with different settings from the export.
    test.each<[string, HogQLQueryModifiers | null, TimestampTimezoneChoice, HogQLQueryModifiers | null]>([
        [
            'keeps other modifiers when it unsets the key',
            { personsOnEventsMode: 'person_id_override_properties_joined', convertToProjectTimezone: false },
            'project_setting',
            { personsOnEventsMode: 'person_id_override_properties_joined' },
        ],
        ['clears the modifiers once no key is left', { convertToProjectTimezone: false }, 'project_setting', null],
        [
            'keeps other modifiers when it sets the key',
            { personsOnEventsMode: 'person_id_override_properties_joined' },
            'project_timezone',
            { personsOnEventsMode: 'person_id_override_properties_joined', convertToProjectTimezone: true },
        ],
        ['adds the key when there are no modifiers', null, 'utc', { convertToProjectTimezone: false }],
    ])('setTimestampTimezone %s', async (_, exportModifiers, choice, expectedModifiers) => {
        await initLogic(undefined, exportModifiers)

        logic.actions.setTimestampTimezone(choice)
        await expectLogic(logic).toFinishAllListeners()

        expect(formLogic.values.configuration.hogql_modifiers).toEqual(expectedModifiers)
        expect(editorLogic().values.queryModifiers).toEqual(expectedModifiers)
    })

    // The form saves `hogql_query`, so it must match what the editor shows. A form reset, such as "Clear changes",
    // must also reach the editor, or the editor keeps text that the form no longer holds.
    it('copies editor changes into the form', async () => {
        await initLogic(undefined, null)

        editorLogic().actions.setQueryInput('SELECT 2')
        await expectLogic(logic).toFinishAllListeners()

        expect(formLogic.values.configuration.hogql_query).toEqual('SELECT 2')
    })

    it('restores the editor when the form resets', async () => {
        await initLogic(undefined, null)
        editorLogic().actions.setQueryInput('SELECT 2')
        await expectLogic(logic).toFinishAllListeners()

        formLogic.actions.resetConfiguration(formLogic.values.savedConfiguration)
        await expectLogic(logic).toFinishAllListeners()

        expect(editorLogic().values.queryInput).toEqual(hogqlExport(null).hogql_query)
    })

    it('gives the editor preview values that follow the schedule', async () => {
        await initLogic(undefined, null)
        const hourlyPlaceholders = editorLogic().values.placeholders
        expect(hourlyPlaceholders).toEqual(logic.values.placeholders)

        formLogic.actions.setConfigurationValue('interval', 'day')
        await expectLogic(logic).toFinishAllListeners()

        expect(editorLogic().values.placeholders).toEqual(logic.values.placeholders)
        expect(editorLogic().values.placeholders).not.toEqual(hourlyPlaceholders)
    })

    it('starts a new export with the default query in both the editor and the form', async () => {
        const newExportProps: BatchExportConfigFormLogicProps = { id: null, service: 'AwsS3' }
        await initLogic(undefined, null, newExportProps)

        const queryInput = editorLogic(newExportProps).values.queryInput
        expect(queryInput).toContain('{data_interval_start}')
        expect(formLogic.values.configuration.hogql_query).toEqual(queryInput)
    })
})
