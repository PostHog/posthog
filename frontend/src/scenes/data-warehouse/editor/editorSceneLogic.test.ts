import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { exportsLogic } from 'lib/components/ExportButton/exportsLogic'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { useMocks } from '~/mocks/jest'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import type { CohortIdentifier } from 'products/data_warehouse/frontend/sql_editor/saveAsTargets'

import { editorSceneLogic } from './editorSceneLogic'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

const TAB_ID = 'editor-scene-test'

describe('editorSceneLogic', () => {
    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team_id/warehouse_saved_queries/': { results: [] },
                '/api/projects/:team_id/external_data_sources/connections/': [],
                '/api/user_home_settings/@me/': {},
            },
            post: {
                '/api/environments/:team_id/query/': [200, { tables: {}, joins: [] }],
            },
        })
        initKeaTests()
        panelLayoutLogic.mount()
    })

    describe('Save as cohort', () => {
        it.each<{ name: string; query: HogQLQuery; identifier: CohortIdentifier; expectedSQL: string }>([
            {
                name: 'wildcard results with variables, filters and an explicit limit',
                identifier: 'person_id',
                expectedSQL:
                    'SELECT person_id FROM (\nSELECT * FROM (SELECT id AS person_id FROM persons WHERE {filters} LIMIT 5)\n) GROUP BY person_id',
                query: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT * FROM (SELECT id AS person_id FROM persons WHERE {filters} LIMIT 5);',
                    variables: { plan: { variableId: 'plan', code_name: 'plan', value: 'pro' } },
                    filters: { filterTestAccounts: true },
                },
            },
            {
                name: 'distinct ID beside an event ID with a bound constant',
                identifier: 'distinct_id',
                expectedSQL:
                    'SELECT distinct_id FROM (\nSELECT uuid AS id, distinct_id FROM events WHERE properties.plan = {plan} -- query end\n) GROUP BY distinct_id',
                query: {
                    kind: NodeKind.HogQLQuery,
                    query: 'SELECT uuid AS id, distinct_id FROM events WHERE properties.plan = {plan} -- query end',
                    values: { plan: 'pro' },
                },
            },
        ])('preserves $name when saving a SQL cohort', async ({ query, identifier, expectedSQL }) => {
            let createdCohort: unknown
            useMocks({
                post: {
                    '/api/cohort/': async ({ request }) => {
                        createdCohort = await request.json()
                        return [201, { id: 42 }]
                    },
                },
            })
            let form: Parameters<typeof LemonDialog.openForm>[0] | undefined
            const openForm = jest.spyOn(LemonDialog, 'openForm').mockImplementation((config) => {
                form = config
            })
            const logic = sqlEditorLogic({ tabId: TAB_ID })
            logic.mount()
            logic.actions.setQueryInput(query.query)
            logic.actions.setSourceQuery({ kind: NodeKind.DataVisualizationNode, source: query })

            const scene = editorSceneLogic({ tabId: TAB_ID })
            scene.mount()
            scene.actions.saveAsCohort(identifier)
            await expectLogic(scene).toFinishAllListeners()

            expect(form).toBeTruthy()
            await expectLogic(exportsLogic(), () => form!.onSubmit({ name: 'Pro people' })).toFinishAllListeners()
            expect(createdCohort).toEqual({
                name: 'Pro people',
                is_static: true,
                query: { ...query, query: expectedSQL },
            })
            openForm.mockRestore()
        })
    })

    // Regression: the collapse must end with the flow, or the nav stays collapsed on the next
    // scene. An embedded editor sits inside another scene and must not collapse that scene's nav.
    it.each([
        ['collapses the app nav for the create view flow in the full scene', undefined, true],
        ['leaves the app nav alone in an embedded editor', SQLEditorMode.Embedded, false],
    ])('%s', (_name, mode, collapsedInFlow) => {
        const props = { tabId: TAB_ID, ...(mode ? { mode } : {}) }
        const logic = editorSceneLogic(props)
        logic.mount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)

        sqlEditorLogic(props).actions.setEditorSource('view')
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(collapsedInFlow)

        logic.unmount()
        expect(panelLayoutLogic.values.isLayoutNavCollapsed).toBe(false)
    })
})
