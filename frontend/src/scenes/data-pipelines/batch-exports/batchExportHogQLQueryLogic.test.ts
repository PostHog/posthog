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
    QueryTimezoneChoice,
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

    // HogQL batch exports resolve `convertToProjectTimezone` from the export's modifiers, then `team.modifiers`, then
    // `false`. The selected option, the preview's placeholder timezone and the modifiers the preview runs with must
    // follow the same order. The preview runs through the query API, which falls back to `true`, so it needs the
    // resolved value, or it shows project-timezone rows for an export that writes UTC. Showing a saved export must not
    // write to its modifiers, or opening it would mark the form as changed.
    test.each<
        [string, HogQLQueryModifiers | undefined, HogQLQueryModifiers | null, QueryTimezoneChoice, string, boolean]
    >([
        ['nothing sets it', undefined, null, 'utc', 'UTC', false],
        ['the team turns it on', { convertToProjectTimezone: true }, null, 'project_timezone', PROJECT_TIMEZONE, true],
        ['the team turns it off', { convertToProjectTimezone: false }, null, 'utc', 'UTC', true],
        [
            'the export turns it on over the team',
            { convertToProjectTimezone: false },
            { convertToProjectTimezone: true },
            'project_timezone',
            PROJECT_TIMEZONE,
            false,
        ],
        [
            'the export turns it off over the team',
            { convertToProjectTimezone: true },
            { convertToProjectTimezone: false },
            'utc',
            'UTC',
            false,
        ],
    ])(
        'resolves the query timezone when %s',
        async (_, teamModifiers, exportModifiers, choice, queryTimezone, followsProjectModifier) => {
            await initLogic(teamModifiers, exportModifiers)

            await expectLogic(logic).toMatchValues({
                queryTimezoneChoice: choice,
                queryTimezone,
                followsProjectModifier,
            })
            const { start, end } = logic.values.previewInterval
            expect(editorLogic().values.placeholders.map((placeholder) => placeholder.previewValue)).toEqual([
                start.tz(queryTimezone).format('YYYY-MM-DD HH:mm:ss'),
                end.tz(queryTimezone).format('YYYY-MM-DD HH:mm:ss'),
            ])
            expect(editorLogic().values.queryModifiers?.convertToProjectTimezone).toBe(queryTimezone !== 'UTC')
            expect(formLogic.values.configuration.hogql_modifiers).toEqual(exportModifiers)
        }
    )

    // The form controls only `convertToProjectTimezone`. Other keys can come from the API, and the backend replaces
    // the whole `hogql_modifiers` object on save, so changing the choice must keep them. Each choice saves an explicit
    // value, so the select always shows what the export does. The editor must get the same modifiers, or the preview
    // runs with different settings from the export.
    test.each<[string, HogQLQueryModifiers | null, QueryTimezoneChoice, HogQLQueryModifiers]>([
        [
            'keeps other modifiers when it sets the key',
            { personsOnEventsMode: 'person_id_override_properties_joined' },
            'project_timezone',
            { personsOnEventsMode: 'person_id_override_properties_joined', convertToProjectTimezone: true },
        ],
        [
            'saves UTC as false rather than removing the key',
            { convertToProjectTimezone: true },
            'utc',
            { convertToProjectTimezone: false },
        ],
        ['saves the option the export already resolves to', null, 'utc', { convertToProjectTimezone: false }],
    ])('setQueryTimezone %s', async (_, exportModifiers, choice, expectedModifiers) => {
        await initLogic(undefined, exportModifiers)

        logic.actions.setQueryTimezone(choice)
        await expectLogic(logic).toFinishAllListeners()

        expect(formLogic.values.configuration.hogql_modifiers).toEqual(expectedModifiers)
        expect(editorLogic().values.queryModifiers).toEqual(expectedModifiers)
    })

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

    it('starts a new export with the default query and an explicit UTC timezone', async () => {
        const newExportProps: BatchExportConfigFormLogicProps = { id: null, service: 'AwsS3' }
        await initLogic(undefined, null, newExportProps)

        const queryInput = editorLogic(newExportProps).values.queryInput
        expect(queryInput).toContain('{data_interval_start}')
        expect(formLogic.values.configuration.hogql_query).toEqual(queryInput)
        expect(formLogic.values.configuration.hogql_modifiers).toEqual({ convertToProjectTimezone: false })
    })
})
