import { act, fireEvent, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import { createElement, createRef } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { DatabaseTree } from '~/layout/panel-layout/DatabaseTree/DatabaseTree'
import { initKeaTests } from '~/test/init'

import {
    addHiddenSelectedConnectionOption,
    connectionSelectorLogic,
    getConnectionSelectOptions,
    getConnectionSelectorValue,
    LOADING_CONNECTIONS,
    POSTHOG_WAREHOUSE,
} from 'products/data_warehouse/frontend/shared/logics/connectionSelectorLogic'
import { externalDataSourcesConnectionsList } from 'products/warehouse_sources/frontend/generated/api'
import type { ExternalDataSourceConnectionOptionApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { QueryWindow } from './QueryWindow'
import { sqlEditorLogic } from './sqlEditorLogic'
import { SQLEditorMode } from './sqlEditorModes'

jest.mock('products/warehouse_sources/frontend/generated/api', () => ({
    externalDataSourcesConnectionsList: jest.fn(),
}))

jest.mock('./sqlEditorLogic', () => {
    const { kea, path, props, key, actions, reducers, selectors } = jest.requireActual('kea')
    return {
        tabModelPath: () => 'test-query.sql',
        sqlEditorLogic: kea([
            path(['test', 'connectionSelectorEditor']),
            props({}),
            key((props: { tabId: string }) => props.tabId),
            actions({
                setSourceQuery: (sourceQuery: unknown) => ({ sourceQuery }),
                syncUrlWithQuery: true,
                setExecutionTarget: true,
                setQueryInput: true,
                runQuery: true,
                runSubquery: true,
                setError: true,
                setMetadata: true,
                setMetadataLoading: true,
                setSendRawQuery: true,
                openMaterializationModal: true,
                setSuggestedQueryInput: true,
                reportAIQueryPromptOpen: true,
                fixIndexUsageWithAI: true,
            }),
            reducers({
                sourceQuery: [
                    { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT 1' } },
                    { setSourceQuery: (_: unknown, { sourceQuery }: { sourceQuery: unknown }) => sourceQuery },
                ],
                queryInput: ['SELECT 1', {}],
                originalQueryInput: [null, {}],
                suggestedQueryInput: ['', {}],
                editingView: [null, {}],
                activeQueryText: [null, {}],
                activeQueryOffset: [0, {}],
                placeholderValues: [null, {}],
                singleStatementDisabledReason: [null, {}],
                rawSqlAllowed: [false, {}],
                sendRawQueryEnabled: [false, {}],
                selectedConnectionSupportsHogQL: [true, {}],
                selectedDirectSource: [null, {}],
            }),
            selectors({
                selectedConnectionId: [
                    (s: any) => [s.sourceQuery],
                    (query: { source: { connectionId?: string } }) => query.source.connectionId,
                ],
            }),
        ]),
    }
})

jest.mock('./editorSizingLogic', () => {
    const { kea, path, actions, reducers } = jest.requireActual('kea')
    return {
        DATABASE_TREE_COLLAPSE_THRESHOLD: 60,
        editorSizingLogic: kea([
            path(['test', 'connectionSelectorSizing']),
            actions({ toggleDatabaseTreeCollapsed: true, setDatabaseTreeCollapsed: true }),
            reducers({
                isDatabaseTreeCollapsed: [false, {}],
                databaseTreeWidth: [300, {}],
                databaseTreeWillCollapse: [false, {}],
                databaseTreeResizerProps: [{}, {}],
                queryPaneDesiredSize: [null, {}],
            }),
        ]),
    }
})

jest.mock('./QueryPane', () => ({ QueryPane: () => null }))
jest.mock('lib/lemon-ui/Resizer/Resizer', () => ({ Resizer: () => null }))
jest.mock('./OutputPane', () => ({ OutputPane: () => null }))
jest.mock('./QueryPlaceholdersMenu', () => ({ QueryPlaceholdersMenu: () => null }))
jest.mock('./sidebar/QueryDatabase', () => ({ QueryDatabase: () => null }))
jest.mock('./sidebar/DatabaseSearchField', () => ({ DatabaseSearchField: () => null }))
jest.mock('~/layout/panel-layout/DatabaseTree/SyncMoreNotice', () => ({ SyncMoreNotice: () => null }))
jest.mock('products/data_warehouse/frontend/shared/components/ViewLinkModal', () => ({ ViewLinkModal: () => null }))
jest.mock('products/data_warehouse/frontend/shared/components/ExpressionModal', () => ({ ExpressionModal: () => null }))
jest.mock('products/posthog_ai/frontend/api/logics', () => ({
    useAttachedContext: () => {},
    useMcpToolApplyBack: () => {},
}))

const mockConnectionsList = externalDataSourcesConnectionsList as jest.Mock

function renderConnectionSelectorSurface(surface: string, hideConnectionSelector = false): void {
    const connectionSelectorConfig = {
        allowedEngines: ['clickhouse'],
        requireHogQL: true,
        showSourceActions: false,
    }
    render(
        surface === 'toolbar'
            ? createElement(QueryWindow, {
                  tabId: 'policy-tab',
                  mode: SQLEditorMode.Embedded,
                  onSetMonacoAndEditor: () => {},
                  showDatabaseTree: false,
                  onShowDatabaseTree: () => {},
                  showOutputPanel: false,
                  hideRunButton: true,
                  hideVariables: true,
                  hideFilters: true,
                  hideAiTools: true,
                  canExpandDatabaseTree: false,
                  hideConnectionSelector,
                  connectionSelectorConfig,
              })
            : createElement(DatabaseTree, {
                  tabId: 'policy-tab',
                  databaseTreeRef: createRef<HTMLDivElement>(),
                  embedded: true,
                  hideConnectionSelector,
                  connectionSelectorConfig,
              })
    )
}

describe('connectionSelectorLogic', () => {
    let logic: ReturnType<typeof connectionSelectorLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockConnectionsList.mockReset().mockResolvedValue([
            {
                id: 'conn-123',
                prefix: 'warehouse',
                engine: 'postgres',
                source_type: 'Postgres',
                access_method: 'direct',
                supports_hogql: true,
                is_builtin_managed_warehouse: false,
            },
            {
                id: 'conn-456',
                prefix: 'prod',
                engine: null,
                source_type: 'MySQL',
                access_method: 'warehouse',
                supports_hogql: true,
                is_builtin_managed_warehouse: false,
            },
            {
                id: 'conn-trino',
                description: 'Managed Warehouse Trino',
                prefix: 'trino',
                engine: 'trino',
                source_type: 'Trino',
                access_method: 'direct',
                supports_hogql: false,
                is_builtin_managed_warehouse: false,
            },
        ])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('does not fetch on mount — embedded editors mount this logic without the selector', async () => {
        logic = connectionSelectorLogic()
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockConnectionsList).not.toHaveBeenCalled()
    })

    it('loads connection options when the selector requests them', async () => {
        logic = connectionSelectorLogic()
        logic.mount()
        logic.actions.maybeLoadConnectionOptions()

        await expectLogic(logic).toFinishAllListeners()

        expect(mockConnectionsList).toHaveBeenCalledTimes(1)
        expect(logic.values.connectionSelectOptions[0].options).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ value: POSTHOG_WAREHOUSE }),
                expect.objectContaining({
                    value: 'conn-123',
                    label: 'warehouse (Postgres)',
                    managementUrl: urls.dataWarehouseSource('managed-conn-123'),
                }),
                // Synced source: no detected engine — label derives from source_type + synced marker
                expect.objectContaining({
                    value: 'conn-456',
                    label: 'prod (MySQL · synced)',
                    managementUrl: urls.dataWarehouseSource('managed-conn-456'),
                }),
                expect.objectContaining({
                    value: 'conn-trino',
                    label: 'Managed Warehouse Trino (Trino)',
                    managementUrl: urls.dataWarehouseSource('managed-conn-trino'),
                }),
            ])
        )
        expect(logic.values.connectionSelectOptions[1].options).toEqual(
            expect.arrayContaining([expect.not.objectContaining({ managementUrl: expect.anything() })])
        )
    })

    it.each([false, true])(
        'keeps the managed connection but hides its menu option with Trino enabled=%s',
        async (enabled) => {
            mockConnectionsList.mockResolvedValue([
                {
                    id: 'conn-duck',
                    prefix: 'managed_warehouse',
                    engine: 'duckdb',
                    source_type: 'Postgres',
                    access_method: 'direct',
                    supports_hogql: true,
                    is_builtin_managed_warehouse: true,
                },
            ])
            logic = connectionSelectorLogic()
            logic.mount()
            featureFlagLogic.actions.setFeatureFlags(enabled ? [FEATURE_FLAGS.MANAGED_TRINO_QUERY] : [], {
                [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: enabled,
            })
            logic.actions.maybeLoadConnectionOptions()

            await expectLogic(logic).toFinishAllListeners()

            const [clickHouseOption, managedWarehouseOption] = logic.values.connectionSelectOptions[0].options
            expect(clickHouseOption).toEqual(
                expect.objectContaining({ value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' })
            )
            expect(managedWarehouseOption).toEqual(
                expect.objectContaining({ value: 'conn-duck', label: 'PostHog (Managed warehouse)', hidden: enabled })
            )
            expect(managedWarehouseOption.iconSrc).toEqual(clickHouseOption.iconSrc)
            expect(managedWarehouseOption).not.toHaveProperty('managementUrl')
            expect(logic.values.connectionOptions).toContainEqual(expect.objectContaining({ id: 'conn-duck' }))
            expect(getConnectionSelectorValue(false, 'conn-duck')).toEqual('conn-duck')

            featureFlagLogic.actions.setFeatureFlags([], {})
            expect(logic.values.connectionSelectOptions[0].options[1].hidden).toBe(false)
        }
    )

    it('keeps the auto-provisioned Duckgres source external when the backend marks it external', async () => {
        mockConnectionsList.mockResolvedValue([
            {
                id: 'conn-duck',
                prefix: 'managed_warehouse',
                description: 'Managed warehouse (auto-provisioned)',
                engine: 'duckdb',
                source_type: 'Postgres',
                access_method: 'direct',
                supports_hogql: true,
                is_builtin_managed_warehouse: false,
            },
        ])
        logic = connectionSelectorLogic()
        logic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MANAGED_TRINO_QUERY], {
            [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: true,
        })
        logic.actions.maybeLoadConnectionOptions()

        await expectLogic(logic).toFinishAllListeners()

        const externalOption = logic.values.connectionSelectOptions[0].options[1]
        expect(externalOption).toEqual(
            expect.objectContaining({
                value: 'conn-duck',
                label: 'Managed warehouse (auto-provisioned) (DuckDB)',
                managementUrl: urls.dataWarehouseSource('managed-conn-duck'),
            })
        )
        expect(externalOption.hidden).toBe(false)
    })

    it('derives the selected connection value from sql editor state', async () => {
        expect(getConnectionSelectorValue(true, undefined)).toEqual(LOADING_CONNECTIONS)
        expect(getConnectionSelectorValue(false, 'conn-123')).toEqual('conn-123')
        expect(getConnectionSelectorValue(false, 'missing')).toEqual('missing')
    })

    it('limits connections by detected engine and HogQL support without offering source actions', async () => {
        const sources = [
            { id: 'clickhouse', engine: 'clickhouse', supports_hogql: true },
            { id: 'raw-clickhouse', engine: 'clickhouse', supports_hogql: false },
            { id: 'postgres', engine: 'postgres', supports_hogql: true },
            { id: 'undetected', engine: null, source_type: 'ClickHouse', supports_hogql: true },
            { id: 'managed', engine: 'clickhouse', supports_hogql: true, is_builtin_managed_warehouse: true },
        ].map((source) => ({
            schema_name: null,
            description: null,
            prefix: null,
            source_type: 'ClickHouse',
            access_method: 'direct',
            is_builtin_managed_warehouse: false,
            ...source,
        })) as ExternalDataSourceConnectionOptionApi[]
        mockConnectionsList.mockResolvedValue(sources)
        logic = connectionSelectorLogic()
        logic.mount()
        logic.actions.maybeLoadConnectionOptions()
        await expectLogic(logic).toFinishAllListeners()

        const options = getConnectionSelectOptions(logic.values.connectionSelectOptions, sources, false, undefined, {
            allowedEngines: ['clickhouse'],
            requireHogQL: true,
            showSourceActions: false,
        })

        expect(options).toEqual([
            {
                options: [
                    expect.objectContaining({ value: POSTHOG_WAREHOUSE }),
                    expect.objectContaining({ value: 'clickhouse' }),
                ],
            },
        ])
        expect(options[0].options.every((option) => !option.managementUrl)).toBe(true)
        expect(logic.values.connectionSelectOptions[0].options).toHaveLength(sources.length + 1)
    })

    it.each([
        ['missing', []],
        ['unsupported', [{ id: 'selected', engine: 'postgres', supports_hogql: true }]],
        ['raw-only', [{ id: 'selected', engine: 'clickhouse', supports_hogql: false }]],
    ])('keeps a %s saved connection visible and disabled', (_name, sources) => {
        const options = getConnectionSelectOptions(
            [{ options: [{ value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' }] }],
            sources as ExternalDataSourceConnectionOptionApi[],
            false,
            'selected',
            { allowedEngines: ['clickhouse'], requireHogQL: true, showSourceActions: false }
        )

        expect(getConnectionSelectorValue(false, 'selected')).toBe('selected')
        expect(options[0].options).toContainEqual(
            expect.objectContaining({
                value: 'selected',
                label: expect.stringContaining('(unavailable)'),
                disabled: true,
                disabledReason: expect.any(String),
            })
        )
    })

    it('shows loading before deciding whether a saved connection is unavailable', () => {
        const options = getConnectionSelectOptions(
            [{ options: [{ value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' }] }],
            null,
            false,
            'selected',
            { requireHogQL: true }
        )

        expect(options[0].options).toContainEqual(
            expect.objectContaining({ value: LOADING_CONNECTIONS, disabled: true })
        )
        expect(options[0].options.some((option) => option.value === 'selected')).toBe(false)
    })

    it.each(['toolbar', 'schema'])('applies the connection policy in the %s picker', async (surface) => {
        mockConnectionsList.mockResolvedValue([
            { id: 'clickhouse', description: 'Analytics', engine: 'clickhouse', supports_hogql: true },
            { id: 'postgres', description: 'Reporting', engine: 'postgres', supports_hogql: true },
        ])
        const unmountFeatureFlags = featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MANAGED_TRINO_QUERY], {
            [FEATURE_FLAGS.MANAGED_TRINO_QUERY]: true,
        })

        try {
            renderConnectionSelectorSurface(surface)
            await act(async () => {
                await expectLogic(connectionSelectorLogic()).toFinishAllListeners()
            })
            fireEvent.click(await screen.findByText('PostHog (ClickHouse)'))

            const clickHouse = await screen.findByText('Analytics (ClickHouse)')
            expect(screen.queryByText('Reporting (Postgres)')).toBeNull()
            expect(screen.queryByText('PostHog (Trino)')).toBeNull()
            expect(screen.queryByText('Configure sources')).toBeNull()
            expect(screen.queryByText('Add direct connection')).toBeNull()
            expect(screen.queryByLabelText('Open settings for Analytics (ClickHouse)')).toBeNull()

            fireEvent.click(clickHouse)
            expect(sqlEditorLogic({ tabId: 'policy-tab' }).values.sourceQuery.source.connectionId).toBe('clickhouse')
        } finally {
            unmountFeatureFlags()
        }
    })

    it.each(['toolbar', 'schema'])('hides the %s picker when requested', (surface) => {
        renderConnectionSelectorSurface(surface, true)

        expect(document.querySelector('[data-attr="sql-editor-connection-selector"]')).toBeNull()
    })

    it.each(['toolbar', 'schema'])('shows a missing saved connection in the %s picker', async (surface) => {
        const editor = sqlEditorLogic({ tabId: 'policy-tab' })
        const unmountEditor = editor.mount()
        editor.actions.setSourceQuery({
            ...editor.values.sourceQuery,
            source: { ...editor.values.sourceQuery.source, connectionId: 'missing' },
        })
        try {
            renderConnectionSelectorSurface(surface)
            await act(async () => {
                await expectLogic(connectionSelectorLogic()).toFinishAllListeners()
            })

            fireEvent.click(await screen.findByText('Selected connection (unavailable)'))
            expect(
                screen
                    .getAllByText('Selected connection (unavailable)')
                    .some((label) => label.closest('button')?.getAttribute('aria-disabled') === 'true')
            ).toBe(true)
            expect(editor.values.sourceQuery.source.connectionId).toBe('missing')

            fireEvent.click(screen.getByText('PostHog (ClickHouse)'))
            expect(editor.values.sourceQuery.source.connectionId).toBeUndefined()
        } finally {
            unmountEditor()
        }
    })

    it.each([
        ['reader after the flag is disabled', 'reader-connection', 'legacy-connection'],
        ['legacy connection after the flag is enabled', 'legacy-connection', 'reader-connection'],
    ])('keeps a hidden selected %s instead of displaying ClickHouse', (_name, selectedId, visibleId) => {
        const optionGroups = [
            {
                options: [
                    { value: POSTHOG_WAREHOUSE, label: 'PostHog (ClickHouse)' },
                    { value: visibleId, label: 'Visible managed warehouse' },
                ],
            },
        ]
        const connectionOptions = [{ id: visibleId }] as ExternalDataSourceConnectionOptionApi[]

        const displayedOptions = addHiddenSelectedConnectionOption(optionGroups, connectionOptions, false, selectedId)

        expect(getConnectionSelectorValue(false, selectedId)).toEqual(selectedId)
        expect(displayedOptions[0].options).toContainEqual({
            value: selectedId,
            label: 'Selected connection (hidden)',
            hidden: true,
        })
    })
})
