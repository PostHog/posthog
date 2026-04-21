import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { ExternalDataSource } from '~/types'

import { projectionEditorLogic } from './projectionEditorLogic'
import { DirectPostgresProjectionRevision, ExternalDataSourceWithProjectionMetadata } from './projectionTypes'
import { sourceSettingsLogic } from './sourceSettingsLogic'

jest.mock('lib/api')

const makeSource = (): ExternalDataSourceWithProjectionMetadata =>
    ({
        id: 'source-1',
        source_type: 'Postgres',
        prefix: 'warehouse',
        access_method: 'direct',
        schemas: [
            {
                id: 'schema-1',
                name: 'public.users',
                label: null,
                should_sync: true,
                incremental: false,
                sync_type: null,
                sync_time_of_day: null,
                latest_error: null,
                incremental_field: null,
                incremental_field_type: null,
                sync_frequency: '6hour',
                primary_key_columns: null,
                source_schema_metadata: {
                    source_catalog: null,
                    source_schema: 'public',
                    source_table_name: 'users',
                    query_name: 'public.users',
                    custom_fields: [],
                    foreign_keys: [],
                    columns: [
                        { name: 'id', data_type: 'integer', is_nullable: false },
                        { name: 'email', data_type: 'text', is_nullable: false },
                    ],
                },
                schema_metadata: {
                    source_catalog: null,
                    source_schema: 'public',
                    source_table_name: 'users',
                    query_name: 'public.users',
                    custom_fields: [],
                    foreign_keys: [],
                    columns: [
                        { name: 'id', data_type: 'integer', is_nullable: false },
                        { name: 'email', data_type: 'text', is_nullable: false },
                    ],
                },
            },
        ],
    }) as unknown as ExternalDataSourceWithProjectionMetadata

const makeRevision = (overrides: Partial<DirectPostgresProjectionRevision> = {}): DirectPostgresProjectionRevision => ({
    id: 'revision-1',
    version: 1,
    config: { tables: [] },
    is_active: true,
    created_at: '2026-04-15T10:00:00Z',
    created_by: 'test@example.com',
    ...overrides,
})

describe('projectionEditorLogic', () => {
    let sourceLogic: ReturnType<typeof sourceSettingsLogic.build>
    let logic: ReturnType<typeof projectionEditorLogic.build>

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()

        jest.spyOn(api.externalDataSources, 'wizard').mockResolvedValue({})
        jest.spyOn(api.externalDataSources, 'get').mockResolvedValue(makeSource() as ExternalDataSource)
        jest.spyOn(api.externalDataSources, 'jobs').mockResolvedValue([])
        jest.spyOn(api.externalDataSources, 'getProjectionRevisions').mockResolvedValue([makeRevision()])
    })

    afterEach(() => {
        logic?.unmount()
        sourceLogic?.unmount()
        featureFlagLogic.unmount()
        jest.restoreAllMocks()
    })

    it('builds and saves projection revisions from the current draft', async () => {
        const createProjectionRevisionSpy = jest
            .spyOn(api.externalDataSources, 'createProjectionRevision')
            .mockResolvedValue([makeRevision({ is_active: false })])

        sourceLogic = sourceSettingsLogic({ id: 'source-1' })
        logic = projectionEditorLogic({ id: 'source-1' })

        sourceLogic.mount()
        logic.mount()

        await expectLogic(sourceLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.syncProjectionState(sourceLogic.values.source)
        logic.actions.setDraftQueryName('schema-1', 'analytics.users')
        logic.actions.toggleRemovedField('schema-1', 'email')
        logic.actions.addCustomField('schema-1')
        logic.actions.updateCustomField('schema-1', 0, 'name', 'domain')
        logic.actions.updateCustomField('schema-1', 0, 'expression', "splitByChar('@', email)[2]")
        logic.actions.saveProjection(false)

        await expectLogic(logic).toFinishAllListeners()

        expect(createProjectionRevisionSpy).toHaveBeenCalledWith(
            'source-1',
            expect.objectContaining({
                activate: false,
                tables: [
                    expect.objectContaining({
                        source_name: 'public.users',
                        source_schema: 'public',
                        source_table_name: 'users',
                        query_name: 'analytics.users',
                        removed_fields: ['email'],
                        custom_fields: [{ name: 'domain', expression: "splitByChar('@', email)[2]" }],
                    }),
                ],
            })
        )
        expect(logic.values.isProjectionDirty).toBe(false)
    })

    it('clears local draft state when activating another revision', async () => {
        jest.spyOn(api.externalDataSources, 'activateProjectionRevision').mockResolvedValue(
            makeRevision({ id: 'revision-2', version: 2 })
        )

        sourceLogic = sourceSettingsLogic({ id: 'source-1' })
        logic = projectionEditorLogic({ id: 'source-1' })

        sourceLogic.mount()
        logic.mount()

        await expectLogic(sourceLogic).toFinishAllListeners()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.syncProjectionState(sourceLogic.values.source)
        logic.actions.setDraftQueryName('schema-1', 'analytics.users')
        logic.actions.activateRevision('revision-2')

        await expectLogic(logic).toFinishAllListeners()

        expect(api.externalDataSources.activateProjectionRevision).toHaveBeenCalledWith('source-1', 'revision-2')
        expect(logic.values.draftTables).toEqual({})
    })
})
