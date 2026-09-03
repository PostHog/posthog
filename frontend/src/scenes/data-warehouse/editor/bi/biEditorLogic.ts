import { MakeLogicType, actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { uuid } from 'lib/utils/dom'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { sqlEditorLogic } from '../sqlEditorLogic'
import type { QueryTab } from '../sqlEditorLogic'
import { captureBIEditorModeSelected } from './biEditorAnalytics'
import {
    BIAggregation,
    BIConfig,
    BIDataSource,
    BIDateBucket,
    BIEditorState,
    BIEditorView,
    BIField,
    BIFilterOperator,
    BIQueryBuildResult,
    BIQueryLimit,
    BIShelf,
    BISort,
    BISortOption,
    DEFAULT_BI_CONFIG,
    buildBIQuery,
    createDefaultDateFilter,
    defaultAggregationForField,
    getBISortOptions,
    isBIFieldCompatible,
    normalizeBIConfig,
} from './biEditorTypes'

export interface BIEditorLogicProps {
    tabId: string
}

function freshBIConfig(): BIConfig {
    return {
        ...DEFAULT_BI_CONFIG,
        rows: [],
        columns: [],
        values: [],
        filters: [],
    }
}

function setDataSourceInConfig(config: BIConfig, source: BIDataSource): BIConfig {
    if (
        config.source?.table === source.table &&
        (config.source.connectionId ?? null) === (source.connectionId ?? null)
    ) {
        return config
    }

    const defaultDateFilter = createDefaultDateFilter(source)

    return {
        ...config,
        source,
        rows: [],
        columns: [],
        values: [],
        filters: defaultDateFilter ? [defaultDateFilter] : [],
        sort: null,
    }
}

function blankField(source: BIDataSource, fieldId: string): BIField {
    return {
        id: fieldId,
        name: '',
        expression: '',
        type: 'unknown',
        source,
    }
}

function addFieldToConfig(config: BIConfig, field: BIField, shelf: BIShelf): BIConfig {
    if (!isBIFieldCompatible(config.source, field)) {
        return config
    }

    const source = config.source ?? field.source
    const sourceConfig = config.source ? config : setDataSourceInConfig(config, source)

    switch (shelf) {
        case 'rows':
        case 'columns':
            if (sourceConfig[shelf].some((existingField) => existingField.id === field.id)) {
                return sourceConfig
            }
            return { ...sourceConfig, source, [shelf]: [...sourceConfig[shelf], field] }
        case 'values':
            return {
                ...sourceConfig,
                source,
                values: [...sourceConfig.values, { field, aggregation: defaultAggregationForField(field) }],
            }
        case 'filters':
            if (
                sourceConfig.filters.some(
                    (filter) =>
                        filter.field.id === field.id ||
                        (filter.field.expression === field.expression &&
                            filter.field.source.table === field.source.table &&
                            (filter.field.source.connectionId ?? null) === (field.source.connectionId ?? null))
                )
            ) {
                return sourceConfig
            }
            return {
                ...sourceConfig,
                source,
                filters: [...sourceConfig.filters, { field, operator: 'equals', value: '' }],
            }
    }
}

function removeFieldFromConfig(config: BIConfig, shelf: BIShelf, index: number): BIConfig {
    switch (shelf) {
        case 'rows':
        case 'columns':
            return { ...config, [shelf]: config[shelf].filter((_, fieldIndex) => fieldIndex !== index) }
        case 'values':
            return { ...config, values: config.values.filter((_, valueIndex) => valueIndex !== index) }
        case 'filters':
            return { ...config, filters: config.filters.filter((_, filterIndex) => filterIndex !== index) }
    }
}

function setFieldExpressionInConfig(config: BIConfig, shelf: BIShelf, index: number, expression: string): BIConfig {
    switch (shelf) {
        case 'rows':
        case 'columns':
            return {
                ...config,
                [shelf]: config[shelf].map((field, fieldIndex) =>
                    fieldIndex === index ? { ...field, expression } : field
                ),
            }
        case 'values':
            return {
                ...config,
                values: config.values.map((value, valueIndex) =>
                    valueIndex === index ? { ...value, field: { ...value.field, expression } } : value
                ),
            }
        case 'filters':
            return {
                ...config,
                filters: config.filters.map((filter, filterIndex) =>
                    filterIndex === index ? { ...filter, field: { ...filter.field, expression } } : filter
                ),
            }
    }
}

function setFieldDateBucketInConfig(
    config: BIConfig,
    shelf: BIShelf,
    index: number,
    dateBucket: BIDateBucket | null
): BIConfig {
    const updateField = (field: BIField): BIField => ({ ...field, dateBucket: dateBucket ?? undefined })

    switch (shelf) {
        case 'rows':
        case 'columns':
            return {
                ...config,
                [shelf]: config[shelf].map((field, fieldIndex) => (fieldIndex === index ? updateField(field) : field)),
            }
        case 'values':
            return {
                ...config,
                values: config.values.map((value, valueIndex) =>
                    valueIndex === index ? { ...value, field: updateField(value.field) } : value
                ),
            }
        case 'filters':
            return {
                ...config,
                filters: config.filters.map((filter, filterIndex) =>
                    filterIndex === index ? { ...filter, field: updateField(filter.field) } : filter
                ),
            }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface biEditorLogicValues {
    allTables: DatabaseSchemaTable[] // databaseTableListLogic
    databaseConnectionId: string | null // databaseTableListLogic
    databaseLoading: boolean // databaseTableListLogic
    posthogTables: DatabaseSchemaTable[] // databaseTableListLogic
    activeTab: QueryTab | null // sqlEditorLogic
    activeDropShelf: BIShelf | null
    activeExpressionEditorId: string | null
    availableDataSources: BIDataSource[]
    config: BIConfig
    editorView: BIEditorView
    generatedQuery: BIQueryBuildResult | null
    sortOptions: BISortOption[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface biEditorLogicActions {
    setSourceQuery: (sourceQuery: import('~/queries/schema/schema-general').DataVisualizationNode) => {
        sourceQuery: import('~/queries/schema/schema-general').DataVisualizationNode
    } // sqlEditorLogic
    syncUrlWithQuery: () => {
        value: true
    } // sqlEditorLogic
    updateTab: (tab: QueryTab) => {
        tab: QueryTab
    } // sqlEditorLogic
    addBlankFieldToShelf: (shelf: BIShelf) => {
        fieldId: string
        shelf: BIShelf
    }
    addFieldToShelf: (
        field: BIField,
        shelf: BIShelf
    ) => {
        field: BIField
        shelf: BIShelf
    }
    clearActiveDropShelf: (shelf: BIShelf) => {
        shelf: BIShelf
    }
    persistState: (
        editorView: BIEditorView,
        config: BIConfig
    ) => {
        config: BIConfig
        editorView: BIEditorView
    }
    removeFieldFromShelf: (
        shelf: BIShelf,
        index: number
    ) => {
        index: number
        shelf: BIShelf
    }
    resetConfig: () => {
        value: true
    }
    restoreState: (state: BIEditorState) => {
        state: BIEditorState
    }
    setActiveDropShelf: (shelf: BIShelf) => {
        shelf: BIShelf
    }
    setActiveExpressionEditorId: (fieldId: string | null) => {
        fieldId: string | null
    }
    setChartType: (chartType: ChartDisplayType) => {
        chartType: ChartDisplayType
    }
    setDataSource: (source: BIDataSource) => {
        source: BIDataSource
    }
    setEditorView: (editorView: BIEditorView) => {
        editorView: BIEditorView
    }
    setFieldDateBucket: (
        shelf: BIShelf,
        index: number,
        dateBucket: BIDateBucket | null
    ) => {
        dateBucket: BIDateBucket | null
        index: number
        shelf: BIShelf
    }
    setFieldExpression: (
        shelf: BIShelf,
        index: number,
        expression: string
    ) => {
        expression: string
        index: number
        shelf: BIShelf
    }
    setFilterCustomExpression: (
        index: number,
        customExpression: string
    ) => {
        customExpression: string
        index: number
    }
    setFilterOperator: (
        index: number,
        operator: BIFilterOperator
    ) => {
        index: number
        operator: BIFilterOperator
    }
    setFilterValue: (
        index: number,
        value: string
    ) => {
        index: number
        value: string
    }
    setLimit: (limit: BIQueryLimit) => {
        limit: 100 | 1000 | 10000 | 50000
    }
    setSort: (sort: BISort | null) => {
        sort: BISort | null
    }
    setValueAggregation: (
        index: number,
        aggregation: BIAggregation
    ) => {
        aggregation: BIAggregation
        index: number
    }
    setValueCustomExpression: (
        index: number,
        customExpression: string
    ) => {
        customExpression: string
        index: number
    }
    syncGeneratedQuery: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface biEditorLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        availableDataSources: (
            allTables: DatabaseSchemaTable[],
            posthogTables: DatabaseSchemaTable[],
            databaseConnectionId: string | null
        ) => BIDataSource[]
        generatedQuery: (config: BIConfig) => BIQueryBuildResult | null
        sortOptions: (config: BIConfig) => BISortOption[]
    }
}

export type biEditorLogicType = MakeLogicType<
    biEditorLogicValues,
    biEditorLogicActions,
    BIEditorLogicProps,
    biEditorLogicMeta
>

export const biEditorLogic = kea<biEditorLogicType>([
    props({} as BIEditorLogicProps),
    key((logicProps) => logicProps.tabId),
    path((logicKey) => ['data-warehouse', 'editor', 'biEditorLogic', logicKey]),
    connect((logicProps: BIEditorLogicProps) => ({
        values: [
            sqlEditorLogic({ tabId: logicProps.tabId }),
            ['activeTab'],
            databaseTableListLogic,
            ['allTables', 'posthogTables', 'connectionId as databaseConnectionId', 'databaseLoading'],
        ],
        actions: [sqlEditorLogic({ tabId: logicProps.tabId }), ['setSourceQuery', 'syncUrlWithQuery', 'updateTab']],
    })),
    actions({
        setEditorView: (editorView: BIEditorView) => ({ editorView }),
        restoreState: (state: BIEditorState) => ({ state }),
        persistState: (editorView: BIEditorView, config: BIConfig) => ({ editorView, config }),
        addFieldToShelf: (field: BIField, shelf: BIShelf) => ({ field, shelf }),
        addBlankFieldToShelf: (shelf: BIShelf) => ({ shelf, fieldId: `bi-blank-${uuid()}` }),
        clearActiveDropShelf: (shelf: BIShelf) => ({ shelf }),
        removeFieldFromShelf: (shelf: BIShelf, index: number) => ({ shelf, index }),
        setActiveDropShelf: (shelf: BIShelf) => ({ shelf }),
        setActiveExpressionEditorId: (fieldId: string | null) => ({ fieldId }),
        setChartType: (chartType: ChartDisplayType) => ({ chartType }),
        setDataSource: (source: BIDataSource) => ({ source }),
        setValueAggregation: (index: number, aggregation: BIAggregation) => ({ index, aggregation }),
        setFilterOperator: (index: number, operator: BIFilterOperator) => ({ index, operator }),
        setFilterValue: (index: number, value: string) => ({ index, value }),
        setLimit: (limit: BIQueryLimit) => ({ limit }),
        setSort: (sort: BISort | null) => ({ sort }),
        setFieldExpression: (shelf: BIShelf, index: number, expression: string) => ({ shelf, index, expression }),
        setFieldDateBucket: (shelf: BIShelf, index: number, dateBucket: BIDateBucket | null) => ({
            shelf,
            index,
            dateBucket,
        }),
        setValueCustomExpression: (index: number, customExpression: string) => ({ index, customExpression }),
        setFilterCustomExpression: (index: number, customExpression: string) => ({ index, customExpression }),
        resetConfig: true,
        syncGeneratedQuery: true,
    }),
    reducers({
        activeDropShelf: [
            null as BIShelf | null,
            {
                setActiveDropShelf: (_, { shelf }) => shelf,
                clearActiveDropShelf: (activeDropShelf, { shelf }) =>
                    activeDropShelf === shelf ? null : activeDropShelf,
            },
        ],
        activeExpressionEditorId: [
            null as string | null,
            {
                addBlankFieldToShelf: (_, { fieldId }) => fieldId,
                setActiveExpressionEditorId: (_, { fieldId }) => fieldId,
                resetConfig: () => null,
                restoreState: () => null,
                setDataSource: () => null,
                setEditorView: () => null,
            },
        ],
        editorView: [
            BIEditorView.SQL as BIEditorView,
            {
                setEditorView: (_, { editorView }) => editorView,
                restoreState: (_, { state }) => state.editorView,
                persistState: (_, { editorView }) => editorView,
                updateTab: (_, { tab }) => tab.biEditorState?.editorView ?? BIEditorView.SQL,
            },
        ],
        config: [
            freshBIConfig(),
            {
                addFieldToShelf: (config, { field, shelf }) => addFieldToConfig(config, field, shelf),
                addBlankFieldToShelf: (config, { shelf, fieldId }) =>
                    config.source ? addFieldToConfig(config, blankField(config.source, fieldId), shelf) : config,
                removeFieldFromShelf: (config, { shelf, index }) => removeFieldFromConfig(config, shelf, index),
                setChartType: (config, { chartType }) => normalizeBIConfig({ ...config, chartType }),
                setDataSource: (config, { source }) => setDataSourceInConfig(config, source),
                setValueAggregation: (config, { index, aggregation }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index ? { ...value, aggregation } : value
                    ),
                }),
                setFilterOperator: (config, { index, operator }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, operator } : filter
                    ),
                }),
                setFilterValue: (config, { index, value }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, value } : filter
                    ),
                }),
                setLimit: (config, { limit }) => normalizeBIConfig({ ...config, limit }),
                setSort: (config, { sort }) => normalizeBIConfig({ ...config, sort }),
                setFieldExpression: (config, { shelf, index, expression }) =>
                    setFieldExpressionInConfig(config, shelf, index, expression),
                setFieldDateBucket: (config, { shelf, index, dateBucket }) =>
                    setFieldDateBucketInConfig(config, shelf, index, dateBucket),
                setValueCustomExpression: (config, { index, customExpression }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index ? { ...value, customExpression } : value
                    ),
                }),
                setFilterCustomExpression: (config, { index, customExpression }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, customExpression } : filter
                    ),
                }),
                restoreState: (_, { state }) => normalizeBIConfig(state.config),
                persistState: (_, { config }) => normalizeBIConfig(config),
                updateTab: (_, { tab }) =>
                    tab.biEditorState ? normalizeBIConfig(tab.biEditorState.config) : freshBIConfig(),
                resetConfig: freshBIConfig,
            },
        ],
    }),
    selectors({
        availableDataSources: [
            (selectors) => [selectors.allTables, selectors.posthogTables, selectors.databaseConnectionId],
            (
                allTables: DatabaseSchemaTable[],
                posthogTables: DatabaseSchemaTable[],
                databaseConnectionId: string | null
            ): BIDataSource[] => {
                const visiblePosthogTableNames = new Set(posthogTables.map((table) => table.name))
                const availableTables = databaseConnectionId
                    ? allTables
                    : allTables.filter((table) => table.type !== 'posthog' || visiblePosthogTableNames.has(table.name))

                return availableTables
                    .map((table) => ({ table: table.name, connectionId: databaseConnectionId ?? undefined }))
                    .sort((first, second) => first.table.localeCompare(second.table))
            },
        ],
        generatedQuery: [
            (selectors) => [selectors.config],
            (config: BIConfig): BIQueryBuildResult | null => buildBIQuery(config),
        ],
        sortOptions: [
            (selectors) => [selectors.config],
            (config: BIConfig): BISortOption[] => getBISortOptions(config),
        ],
    }),
    listeners(({ actions, props: logicProps, values }) => ({
        persistState: ({ editorView, config }) => {
            if (!values.activeTab) {
                return
            }
            actions.updateTab({
                ...values.activeTab,
                biEditorState: { editorView, config },
            })
            actions.syncUrlWithQuery()
        },
        setEditorView: ({ editorView }) => {
            captureBIEditorModeSelected(editorView, values.config)
            actions.persistState(editorView, values.config)
            if (editorView === BIEditorView.BI) {
                actions.syncGeneratedQuery()
            }
        },
        addFieldToShelf: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        addBlankFieldToShelf: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        removeFieldFromShelf: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setChartType: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setDataSource: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setValueAggregation: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setFilterOperator: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setFilterValue: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setLimit: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setSort: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setFieldExpression: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setFieldDateBucket: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setValueCustomExpression: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setFilterCustomExpression: () => {
            actions.persistState(values.editorView, values.config)
            actions.syncGeneratedQuery()
        },
        setSourceQuery: ({ sourceQuery }) => {
            if (!values.activeTab?.biEditorState && values.editorView === BIEditorView.SQL) {
                return
            }
            actions.persistState(values.editorView, {
                ...values.config,
                chartType: sourceQuery.display ?? values.config.chartType,
            })
        },
        resetConfig: () => {
            actions.persistState(values.editorView, values.config)
            const editorLogic = sqlEditorLogic({ tabId: logicProps.tabId })
            const sourceQuery = editorLogic.values.sourceQuery
            editorLogic.actions.setQueryInput('')
            editorLogic.actions.setSourceQuery({
                ...sourceQuery,
                display: DEFAULT_BI_CONFIG.chartType,
                source: { ...sourceQuery.source, query: '' },
            })
        },
        syncGeneratedQuery: () => {
            if (!values.generatedQuery) {
                return
            }

            const editorLogic = sqlEditorLogic({ tabId: logicProps.tabId })
            const sourceQuery = editorLogic.values.sourceQuery
            const generatedChartSettings = values.generatedQuery.node.chartSettings
            editorLogic.actions.setQueryInput(values.generatedQuery.query)
            editorLogic.actions.setSourceQuery({
                ...sourceQuery,
                ...values.generatedQuery.node,
                chartSettings: generatedChartSettings
                    ? {
                          ...sourceQuery.chartSettings,
                          ...generatedChartSettings,
                          heatmap: {
                              ...sourceQuery.chartSettings?.heatmap,
                              ...generatedChartSettings.heatmap,
                          },
                      }
                    : sourceQuery.chartSettings,
                source: {
                    ...sourceQuery.source,
                    ...values.generatedQuery.node.source,
                },
            })
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.activeTab?.biEditorState) {
            actions.restoreState(values.activeTab.biEditorState)
        }
    }),
])
