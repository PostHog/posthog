import { expectLogic } from 'kea-test-utils'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { createAccountSqlVisualizationNode } from './accountSqlQuery'
import { accountSqlQueryEditorLogic } from './accountSqlQueryEditorLogic'
import type { AccountViewTileConfig } from './accountViewTileConfig'

jest.mock('lib/utils/kea-logic-builders', () => ({
    permanentlyMount: () => () => {},
}))

describe('accountSqlQueryEditorLogic', () => {
    const connectionId = '11111111-1111-4111-8111-111111111111'
    const otherConnectionId = '22222222-2222-4222-8222-222222222222'
    const query = 'select * from example_engagements where org_id = {account_external_id}'
    const visualization = {
        display: ChartDisplayType.ActionsLineGraph,
        chartSettings: { showLegend: false },
    }
    let unmounts: (() => void)[]

    beforeEach(() => {
        initKeaTests()
        unmounts = []
        useMocks({
            get: {
                '/api/projects/:project_id/accounts/:account_id/': ({ params }) => ({
                    id: params.account_id,
                    name: 'Example account',
                    external_id: `example-org-${params.account_id}`,
                    properties: {},
                    notebooks: [],
                }),
            },
        })
    })

    afterEach(() => unmounts.reverse().forEach((unmount) => unmount()))

    async function mountEditor(
        config: AccountViewTileConfig,
        tabId = 'first-tile',
        accountId = 'one'
    ): Promise<{
        logic: ReturnType<typeof accountSqlQueryEditorLogic.build>
        editor: ReturnType<typeof sqlEditorLogic.build>
        onChange: jest.Mock
    }> {
        const onChange = jest.fn()
        const logic = accountSqlQueryEditorLogic({
            tabId,
            projectId: 1,
            accountId,
            config,
            saving: false,
            onChange,
        })
        await expectLogic(logic, () => {
            unmounts.push(logic.mount())
        }).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({
            account: expect.objectContaining({ external_id: `example-org-${accountId}` }),
        })
        const editor = sqlEditorLogic({ tabId, mode: SQLEditorMode.Embedded, captureQueryTelemetry: false })
        return { logic, editor, onChange }
    }

    it.each([undefined, connectionId])('restores %s without writing config on mount', async (sourceId) => {
        const config = { query, visualization, ...(sourceId ? { connectionId: sourceId } : {}) }
        const { logic, editor, onChange } = await mountEditor(config)

        expect(onChange).not.toHaveBeenCalled()
        expect(editor.values.sourceQuery).toEqual(
            createAccountSqlVisualizationNode(
                { kind: NodeKind.HogQLQuery, query, ...(sourceId ? { connectionId: sourceId } : {}) },
                config
            )
        )
        expect(editor.values.placeholders).toEqual([
            { name: 'account_external_id', description: 'The current account', previewValue: 'example-org-one' },
        ])
        logic.actions.runPreview()
        expect(logic.values.previewConfig).toEqual(config)
    })

    it('preserves the source through SQL edits, chart edits, and a saved config round trip', async () => {
        const { logic, editor, onChange } = await mountEditor({ query, visualization })
        const updatedQuery = `${query} limit 5`
        const updatedVisualization = { display: ChartDisplayType.ActionsBar, chartSettings: { showLegend: true } }

        await expectLogic(logic, () => {
            editor.actions.setSourceQuery({
                ...editor.values.sourceQuery,
                source: { kind: NodeKind.HogQLQuery, query, connectionId },
            })
            editor.actions.setQueryInput(updatedQuery)
            logic.actions.setVisualization(
                createAccountSqlVisualizationNode(
                    { kind: NodeKind.HogQLQuery, query: updatedQuery },
                    { visualization: updatedVisualization }
                )
            )
        }).toFinishAllListeners()

        const savedConfig = onChange.mock.calls.at(-1)?.[0]
        expect(savedConfig).toEqual({ query: updatedQuery, connectionId, visualization: updatedVisualization })
        logic.actions.runPreview()
        expect(logic.values.previewConfig).toEqual(savedConfig)

        const restored = await mountEditor(savedConfig, 'restored-tile', 'two')
        expect(restored.editor.values.sourceQuery.source).toEqual({
            kind: NodeKind.HogQLQuery,
            query: updatedQuery,
            connectionId,
        })
        expect(restored.editor.values.placeholders[0].previewValue).toBe('example-org-two')
        expect(restored.onChange).not.toHaveBeenCalled()
    })

    it.each([otherConnectionId, undefined])(
        'clears only the changed tile preview when switching to %s',
        async (nextId) => {
            const first = await mountEditor({ query, connectionId, visualization })
            const second = await mountEditor({ query }, 'second-tile')
            first.logic.actions.runPreview()
            second.logic.actions.runPreview()
            const secondPreview = second.logic.values.previewConfig

            first.editor.actions.setSourceQuery({
                ...first.editor.values.sourceQuery,
                source: { kind: NodeKind.HogQLQuery, query, connectionId: nextId },
            })

            expect(first.logic.values.previewConfig).toBeNull()
            expect(second.logic.values.previewConfig).toEqual(secondPreview)
            first.logic.actions.runPreview()
            expect(first.logic.values.previewConfig).toEqual({
                query,
                visualization,
                ...(nextId ? { connectionId: nextId } : {}),
            })
            expect(first.onChange.mock.calls.at(-1)?.[0]).toEqual(first.logic.values.previewConfig)
            expect(second.onChange).not.toHaveBeenCalled()

            first.editor.actions.setQueryInput(`${query} limit 5`)
            expect(first.logic.values.previewConfig).toBeNull()
        }
    )

    it('blocks a malformed saved connection until another source is selected', async () => {
        const config = { query, connectionId: 123 }
        const { logic, editor, onChange } = await mountEditor(config)
        logic.actions.runPreview()
        expect(logic.values.previewConfig).toBeNull()
        expect(logic.values.config).toEqual(config)
        expect(onChange).not.toHaveBeenCalled()
        expect(editor.values.queryInput).toEqual(query)

        editor.actions.setSourceQuery({
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query, connectionId },
        })
        logic.actions.runPreview()
        expect(logic.values.previewConfig).toEqual({
            query,
            connectionId,
            visualization: { display: ChartDisplayType.ActionsTable },
        })
    })
})
