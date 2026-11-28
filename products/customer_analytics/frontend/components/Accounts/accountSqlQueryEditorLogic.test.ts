import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { useMocks } from '~/mocks/jest'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import {
    getConnectionSelectOptions,
    getConnectionSelectorValue,
    POSTHOG_WAREHOUSE,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'

import { createAccountSqlVisualizationNode } from './accountSqlQuery'
import { accountSqlQueryEditorLogic } from './accountSqlQueryEditorLogic'
import type { AccountViewTileConfig } from './accountViewTileConfig'
import { AccountsEvents } from './constants'

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

    afterEach(() => {
        unmounts.reverse().forEach((unmount) => unmount())
        jest.restoreAllMocks()
    })

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

    it.each(
        [123, connectionId.replace(/-/g, ''), 'not-a-uuid', '', POSTHOG_WAREHOUSE].flatMap((invalidId) =>
            [undefined, connectionId].map((nextId) => [invalidId, nextId] as const)
        )
    )('blocks saved connection %s across the restricted editor mount until selecting %s', async (invalidId, nextId) => {
        const capture = jest.spyOn(posthog, 'capture')
        const config = { query, connectionId: invalidId, visualization }
        const { logic, editor, onChange } = await mountEditor(config)
        const restrictedBinding = sqlEditorLogic({
            tabId: logic.props.tabId,
            mode: SQLEditorMode.Embedded,
            captureQueryTelemetry: false,
            allowRawSql: false,
        })
        await expectLogic(logic, () => {
            unmounts.push(restrictedBinding.mount())
        }).toFinishAllListeners()
        expect(restrictedBinding.values.rawSqlAllowed).toBe(false)
        logic.actions.runPreview()
        expect(logic.values.previewConfig).toBeNull()
        expect(logic.values.config).toEqual(config)
        expect(onChange).not.toHaveBeenCalled()
        expect(editor.values.queryInput).toEqual(query)
        const selectedValue = getConnectionSelectorValue(false, editor.values.selectedConnectionId)
        const connectionOptions = getConnectionSelectOptions(
            [{ options: [{ value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' }] }],
            [],
            false,
            editor.values.selectedConnectionId,
            { allowedEngines: ['clickhouse'], requireHogQL: true, showSourceActions: false }
        )
        expect(selectedValue).not.toBe(POSTHOG_WAREHOUSE)
        expect(connectionOptions[0].options).toContainEqual(
            expect.objectContaining({
                value: selectedValue,
                label: 'Selected connection (unavailable)',
                disabled: true,
            })
        )
        expect(capture).not.toHaveBeenCalledWith(AccountsEvents.SqlQueryConnectionSelected, expect.anything())

        editor.actions.setSourceQuery({
            ...editor.values.sourceQuery,
            source: { ...editor.values.sourceQuery.source, connectionId: nextId },
        })
        logic.actions.runPreview()
        const expectedConfig = {
            query,
            ...(nextId ? { connectionId: nextId } : {}),
            visualization,
        }
        expect(logic.values.config).toStrictEqual(expectedConfig)
        expect(onChange.mock.calls.at(-1)?.[0]).toEqual(logic.values.config)
        expect(logic.values.previewConfig).toEqual(expectedConfig)
        expect(getConnectionSelectorValue(false, editor.values.selectedConnectionId)).toBe(nextId ?? POSTHOG_WAREHOUSE)
        expect(editor.values.placeholders).toEqual([
            { name: 'account_external_id', description: 'The current account', previewValue: 'example-org-one' },
        ])
        expect(capture).toHaveBeenCalledWith(AccountsEvents.SqlQueryConnectionSelected, {
            source_kind: nextId ? 'clickhouse' : 'posthog',
        })
    })
})
