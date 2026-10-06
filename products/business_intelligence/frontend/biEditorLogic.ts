import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { uuid } from 'lib/utils/dom'
import { TableFieldsStatus, databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import {
    BIAggregation,
    BIConfig,
    BIDataSource,
    BIDateBucket,
    BIField,
    BIFilter,
    BIFilterOperator,
    BIQueryLimit,
    BISort,
} from '~/queries/schema/schema-business-intelligence'
import { CompareFilter, DatabaseSchemaTable, DateRange } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { captureBIEditorModeSelected } from 'products/business_intelligence/frontend/biEditorAnalytics'
import {
    BIChartFit,
    BIDataPaneFields,
    BIEditorState,
    BIEditorView,
    BIQueryBuildResult,
    BIShelf,
    BISortOption,
    DEFAULT_BI_CONFIG,
    buildBIQuery,
    changeBIFilterOperator,
    createDefaultDateFilter,
    defaultAggregationForField,
    getBIChartFit,
    getBIDataPaneFields,
    getBIDataSourceKey,
    getBIShelfEditorKey,
    getBISortOptions,
    isBIFieldCompatible,
    normalizeBIConfig,
} from 'products/business_intelligence/frontend/biEditorTypes'

import { matchesBIFieldSearch } from './biPropertyFields'
import { getBIDateField } from './biQueryFilters'

export interface BIEditorLogicProps {
    tabId: string
}

export interface BICalculatedMeasureDraft {
    index: number | null
    name: string
    expression: string
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
        filters: [],
        dateField: defaultDateFilter?.field ?? getBIDateField({ ...config, source, dateField: undefined }),
        dateRange: { date_from: defaultDateFilter ? '-7d' : 'all' },
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
                filters: [
                    ...sourceConfig.filters,
                    { field, operator: field.type === 'string' ? 'in' : 'equals', value: '' },
                ],
            }
    }
}

function fieldOnShelf(config: BIConfig, shelf: BIShelf, index: number): BIField | null {
    switch (shelf) {
        case 'rows':
        case 'columns':
            return config[shelf][index] ?? null
        case 'values':
            return config.values[index]?.field ?? null
        case 'filters':
            return config.filters[index]?.field ?? null
    }
}

function moveFieldInConfig(config: BIConfig, fromShelf: BIShelf, fromIndex: number, toShelf: BIShelf): BIConfig {
    if (fromShelf === 'values' && config.values[fromIndex]?.label) {
        return config
    }
    const field = fieldOnShelf(config, fromShelf, fromIndex)
    if (!field || fromShelf === toShelf) {
        return config
    }

    return addFieldToConfig(removeFieldFromConfig(config, fromShelf, fromIndex), field, toShelf)
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
    const updateField = (field: BIField): BIField => ({ ...field, expression, name: expression.trim() })
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
    tableFieldsStatus: TableFieldsStatus // databaseTableListLogic
    activeDropShelf: BIShelf | null
    activeExpressionEditorId: string | null
    activeExpressionEditorTarget: 'aggregation' | 'field'
    autoUpdate: boolean
    availableDataSources: BIDataSource[]
    calculatedMeasureDraft: BICalculatedMeasureDraft | null
    chartFits: Partial<Record<ChartDisplayType, BIChartFit>>
    config: BIConfig
    dataPaneFields: BIDataPaneFields
    dataPaneFieldsError: boolean
    dataPaneFieldsLoading: boolean
    dataPaneSearch: string
    dragSessionId: string
    editorView: BIEditorView
    filteredDataPaneFields: BIDataPaneFields
    generatedQuery: BIQueryBuildResult | null
    hoveredChartType: ChartDisplayType | null
    selectableDataSources: BIDataSource[]
    showMeOpen: boolean
    sortOptions: BISortOption[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface biEditorLogicActions {
    hydrateTableFields: (tableNames: string[]) => {
        tableNames: string[]
    } // databaseTableListLogic
    loadDatabaseSuccess: (
        database: Required<import('~/queries/schema').DatabaseSchemaQueryResponse> | null,
        payload?:
            | {
                  force?: boolean
                  shallow?: boolean
              }
            | undefined
    ) => {
        database: Required<import('~/queries/schema').DatabaseSchemaQueryResponse> | null
        payload?: {
            force?: boolean
            shallow?: boolean
        }
    } // databaseTableListLogic
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
    editCalculatedMeasure: (index?: number | null) => {
        index: number | null
    }
    moveFieldToShelf: (
        fromShelf: BIShelf,
        fromIndex: number,
        toShelf: BIShelf
    ) => {
        fromIndex: number
        fromShelf: BIShelf
        toShelf: BIShelf
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
    runAfterChange: () => {
        value: true
    }
    saveCalculatedMeasure: () => {
        value: true
    }
    setActiveDropShelf: (shelf: BIShelf | null) => {
        shelf: BIShelf | null
    }
    setActiveExpressionEditorId: (
        fieldId: string | null,
        target?: 'aggregation' | 'field'
    ) => {
        fieldId: string | null
        target: 'aggregation' | 'field'
    }
    setAutoUpdate: (autoUpdate: boolean) => {
        autoUpdate: boolean
    }
    setCalculatedMeasureDraft: (draft: BICalculatedMeasureDraft | null) => {
        draft: BICalculatedMeasureDraft | null
    }
    setChartType: (chartType: ChartDisplayType) => {
        chartType: ChartDisplayType
    }
    setCompareFilter: (compareFilter: CompareFilter) => {
        compareFilter: CompareFilter
    }
    setDataPaneSearch: (search: string) => {
        search: string
    }
    setDataSource: (source: BIDataSource) => {
        source: BIDataSource
    }
    setDateField: (field: BIField | null) => {
        field: BIField | null
    }
    setDateRange: (dateRange: DateRange) => {
        dateRange: DateRange
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
    setHoveredChartType: (chartType: ChartDisplayType | null) => {
        chartType: ChartDisplayType | null
    }
    setLimit: (limit: BIQueryLimit) => {
        limit: BIQueryLimit
    }
    setShowMeOpen: (showMeOpen: boolean) => {
        showMeOpen: boolean
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
    swapRowsAndColumns: () => {
        value: true
    }
    updateFilter: (
        index: number,
        update: Partial<Pick<BIFilter, 'enabled' | 'values' | 'valueTo'>>
    ) => {
        index: number
        update: Partial<Pick<BIFilter, 'enabled' | 'values' | 'valueTo'>>
    }
    upsertCalculatedMeasure: (draft: BICalculatedMeasureDraft) => {
        draft: BICalculatedMeasureDraft
        fieldId: string
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
        selectableDataSources: (availableDataSources: BIDataSource[], config: BIConfig) => BIDataSource[]
        generatedQuery: (config: BIConfig) => BIQueryBuildResult | null
        sortOptions: (config: BIConfig) => BISortOption[]
        chartFits: (config: BIConfig) => Partial<Record<ChartDisplayType, BIChartFit>>
        dataPaneFields: (
            config: BIConfig,
            allTables: DatabaseSchemaTable[],
            databaseConnectionId: string | null
        ) => BIDataPaneFields
        dataPaneFieldsLoading: (
            config: BIConfig,
            tableFieldsStatus: TableFieldsStatus,
            databaseLoading: boolean,
            databaseConnectionId: string | null
        ) => boolean
        dataPaneFieldsError: (
            config: BIConfig,
            tableFieldsStatus: TableFieldsStatus,
            databaseConnectionId: string | null
        ) => boolean
        filteredDataPaneFields: (dataPaneFields: BIDataPaneFields, dataPaneSearch: string) => BIDataPaneFields
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
    path((logicKey) => ['products', 'business_intelligence', 'biEditorLogic', logicKey]),
    connect(() => ({
        values: [
            databaseTableListLogic,
            [
                'allTables',
                'posthogTables',
                'connectionId as databaseConnectionId',
                'databaseLoading',
                'tableFieldsStatus',
            ],
        ],
        actions: [databaseTableListLogic, ['hydrateTableFields', 'loadDatabaseSuccess']],
    })),
    actions({
        setEditorView: (editorView: BIEditorView) => ({ editorView }),
        restoreState: (state: BIEditorState) => ({ state }),
        addFieldToShelf: (field: BIField, shelf: BIShelf) => ({ field, shelf }),
        addBlankFieldToShelf: (shelf: BIShelf) => ({ shelf, fieldId: `bi-blank-${uuid()}` }),
        editCalculatedMeasure: (index: number | null = null) => ({ index }),
        setCalculatedMeasureDraft: (draft: BICalculatedMeasureDraft | null) => ({ draft }),
        saveCalculatedMeasure: true,
        upsertCalculatedMeasure: (draft: BICalculatedMeasureDraft) => ({ draft, fieldId: `bi-calculated-${uuid()}` }),
        clearActiveDropShelf: (shelf: BIShelf) => ({ shelf }),
        moveFieldToShelf: (fromShelf: BIShelf, fromIndex: number, toShelf: BIShelf) => ({
            fromShelf,
            fromIndex,
            toShelf,
        }),
        swapRowsAndColumns: true,
        setAutoUpdate: (autoUpdate: boolean) => ({ autoUpdate }),
        setShowMeOpen: (showMeOpen: boolean) => ({ showMeOpen }),
        setHoveredChartType: (chartType: ChartDisplayType | null) => ({ chartType }),
        setDataPaneSearch: (search: string) => ({ search }),
        runAfterChange: true,
        removeFieldFromShelf: (shelf: BIShelf, index: number) => ({ shelf, index }),
        setActiveDropShelf: (shelf: BIShelf | null) => ({ shelf }),
        setActiveExpressionEditorId: (fieldId: string | null, target: 'field' | 'aggregation' = 'field') => ({
            fieldId,
            target,
        }),
        setChartType: (chartType: ChartDisplayType) => ({ chartType }),
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setDateField: (field: BIField | null) => ({ field }),
        setDataSource: (source: BIDataSource) => ({ source }),
        setValueAggregation: (index: number, aggregation: BIAggregation) => ({ index, aggregation }),
        setFilterOperator: (index: number, operator: BIFilterOperator) => ({ index, operator }),
        setFilterValue: (index: number, value: string) => ({ index, value }),
        updateFilter: (index: number, update: Partial<Pick<BIFilter, 'values' | 'valueTo' | 'enabled'>>) => ({
            index,
            update,
        }),
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
    }),
    reducers(() => ({
        calculatedMeasureDraft: [
            null as BICalculatedMeasureDraft | null,
            {
                setCalculatedMeasureDraft: (_, { draft }) => draft,
                upsertCalculatedMeasure: () => null,
                setDataSource: () => null,
                resetConfig: () => null,
                restoreState: () => null,
                setEditorView: () => null,
                removeFieldFromShelf: () => null,
                moveFieldToShelf: () => null,
            },
        ],
        dragSessionId: [uuid(), {}],
        activeDropShelf: [
            null as BIShelf | null,
            {
                setActiveDropShelf: (_, { shelf }) => shelf,
                clearActiveDropShelf: (activeDropShelf, { shelf }) =>
                    activeDropShelf === shelf ? null : activeDropShelf,
            },
        ],
        autoUpdate: [true, { persist: true }, { setAutoUpdate: (_, { autoUpdate }) => autoUpdate }],
        showMeOpen: [true, { persist: true }, { setShowMeOpen: (_, { showMeOpen }) => showMeOpen }],
        hoveredChartType: [
            null as ChartDisplayType | null,
            { setHoveredChartType: (_, { chartType }) => chartType, setShowMeOpen: () => null },
        ],
        activeExpressionEditorTarget: [
            'field' as 'field' | 'aggregation',
            {
                setActiveExpressionEditorId: (_, { target }) => target,
                addBlankFieldToShelf: () => 'field',
                addFieldToShelf: () => 'field',
            },
        ],
        dataPaneSearch: [
            '',
            {
                setDataPaneSearch: (_, { search }) => search,
                setDataSource: () => '',
            },
        ],
        activeExpressionEditorId: [
            null as string | null,
            {
                addBlankFieldToShelf: (_, { shelf, fieldId }) => getBIShelfEditorKey(shelf, fieldId),
                // Opens the filter editor as soon as a field lands on the filters shelf
                addFieldToShelf: (activeExpressionEditorId, { field, shelf }) =>
                    shelf === 'filters' ? getBIShelfEditorKey('filters', field.id) : activeExpressionEditorId,
                setActiveExpressionEditorId: (_, { fieldId }) => fieldId,
                resetConfig: () => null,
                restoreState: () => null,
                removeFieldFromShelf: () => null,
                moveFieldToShelf: () => null,
                swapRowsAndColumns: () => null,
                setDataSource: () => null,
                setEditorView: () => null,
            },
        ],
        editorView: [
            BIEditorView.BI as BIEditorView,
            {
                setEditorView: (_, { editorView }) => editorView,
                restoreState: (_, { state }) => state.editorView,
            },
        ],
        config: [
            freshBIConfig(),
            {
                upsertCalculatedMeasure: (config, { draft, fieldId }) => {
                    if (!config.source) {
                        return config
                    }
                    const existing = draft.index === null ? null : config.values[draft.index]
                    const value = {
                        field: existing?.field ?? { ...blankField(config.source, fieldId), type: 'float' as const },
                        aggregation: 'custom' as const,
                        customExpression: draft.expression.trim(),
                        label: draft.name.trim(),
                    }
                    return {
                        ...config,
                        values:
                            draft.index === null
                                ? [...config.values, value]
                                : config.values.map((current, index) => (index === draft.index ? value : current)),
                    }
                },
                addFieldToShelf: (config, { field, shelf }) => addFieldToConfig(config, field, shelf),
                addBlankFieldToShelf: (config, { shelf, fieldId }) =>
                    config.source ? addFieldToConfig(config, blankField(config.source, fieldId), shelf) : config,
                removeFieldFromShelf: (config, { shelf, index }) => removeFieldFromConfig(config, shelf, index),
                moveFieldToShelf: (config, { fromShelf, fromIndex, toShelf }) =>
                    normalizeBIConfig(moveFieldInConfig(config, fromShelf, fromIndex, toShelf)),
                swapRowsAndColumns: (config) =>
                    normalizeBIConfig({ ...config, rows: config.columns, columns: config.rows }),
                setChartType: (config, { chartType }) => normalizeBIConfig({ ...config, chartType }),
                setDateRange: (config, { dateRange }) => ({ ...config, dateRange }),
                setCompareFilter: (config, { compareFilter }) => ({ ...config, compareFilter }),
                setDateField: (config, { field }) => ({ ...config, dateField: field }),
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
                        filterIndex === index ? changeBIFilterOperator(filter, operator) : filter
                    ),
                }),
                setFilterValue: (config, { index, value }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, value } : filter
                    ),
                }),
                updateFilter: (config, { index, update }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, ...update } : filter
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
                resetConfig: freshBIConfig,
            },
        ],
    })),
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
        selectableDataSources: [
            (selectors) => [selectors.availableDataSources, selectors.config],
            (availableDataSources: BIDataSource[], config: BIConfig): BIDataSource[] => {
                const source = config.source
                // Keeps the chosen table selectable while tables load, or after it leaves the list
                return !source ||
                    availableDataSources.some(
                        (candidate) => getBIDataSourceKey(candidate) === getBIDataSourceKey(source)
                    )
                    ? availableDataSources
                    : [source, ...availableDataSources]
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
        chartFits: [
            (selectors) => [selectors.config],
            (config: BIConfig): Partial<Record<ChartDisplayType, BIChartFit>> =>
                Object.fromEntries(
                    Object.values(ChartDisplayType).map((chartType) => [chartType, getBIChartFit(config, chartType)])
                ),
        ],
        dataPaneFields: [
            (selectors) => [selectors.config, selectors.allTables, selectors.databaseConnectionId],
            (
                config: BIConfig,
                allTables: DatabaseSchemaTable[],
                databaseConnectionId: string | null
            ): BIDataPaneFields =>
                config.source && (config.source.connectionId ?? null) === databaseConnectionId
                    ? getBIDataPaneFields(
                          allTables.find((table) => table.name === config.source?.table),
                          config.source
                      )
                    : { dimensions: [], measures: [] },
        ],
        dataPaneFieldsLoading: [
            (selectors) => [
                selectors.config,
                selectors.tableFieldsStatus,
                selectors.databaseLoading,
                selectors.databaseConnectionId,
            ],
            (
                config: BIConfig,
                tableFieldsStatus: TableFieldsStatus,
                databaseLoading: boolean,
                connectionId: string | null
            ): boolean =>
                !!config.source &&
                (config.source.connectionId ?? null) === connectionId &&
                (databaseLoading || tableFieldsStatus[config.source.table] === 'loading'),
        ],
        dataPaneFieldsError: [
            (selectors) => [selectors.config, selectors.tableFieldsStatus, selectors.databaseConnectionId],
            (config: BIConfig, tableFieldsStatus: TableFieldsStatus, connectionId: string | null): boolean =>
                !!config.source &&
                (config.source.connectionId ?? null) === connectionId &&
                tableFieldsStatus[config.source.table] === 'error',
        ],
        filteredDataPaneFields: [
            (selectors) => [selectors.dataPaneFields, selectors.dataPaneSearch],
            (dataPaneFields: BIDataPaneFields, dataPaneSearch: string): BIDataPaneFields => {
                const needle = dataPaneSearch.trim().toLowerCase()
                if (!needle) {
                    return dataPaneFields
                }
                const matches = (field: BIField): boolean => matchesBIFieldSearch(field, needle)
                return {
                    dimensions: dataPaneFields.dimensions.filter(matches),
                    measures: dataPaneFields.measures.filter(matches),
                }
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        editCalculatedMeasure: ({ index }) => {
            if (!values.config.source) {
                return
            }
            const value = index === null ? null : values.config.values[index]
            actions.setActiveExpressionEditorId(null)
            actions.setCalculatedMeasureDraft({
                index,
                name: value?.label ?? '',
                expression: value?.customExpression ?? '',
            })
        },
        saveCalculatedMeasure: () => {
            const draft = values.calculatedMeasureDraft
            if (draft?.name.trim() && draft.expression.trim()) {
                actions.upsertCalculatedMeasure(draft)
            }
        },
        upsertCalculatedMeasure: () => actions.runAfterChange(),
        loadDatabaseSuccess: () => {
            if (values.config.source && (values.config.source.connectionId ?? null) === values.databaseConnectionId) {
                actions.hydrateTableFields([values.config.source.table])
            }
        },
        setEditorView: ({ editorView }) => {
            captureBIEditorModeSelected(editorView, values.config)
        },
        addFieldToShelf: () => actions.runAfterChange(),
        moveFieldToShelf: () => actions.runAfterChange(),
        swapRowsAndColumns: () => actions.runAfterChange(),
        setAutoUpdate: ({ autoUpdate }) => {
            if (autoUpdate) {
                actions.runAfterChange()
            }
        },
        addBlankFieldToShelf: () => actions.runAfterChange(),
        removeFieldFromShelf: () => actions.runAfterChange(),
        setChartType: () => actions.runAfterChange(),
        setDateRange: () => actions.runAfterChange(),
        setCompareFilter: () => actions.runAfterChange(),
        setDateField: () => actions.runAfterChange(),
        setDataSource: () => actions.runAfterChange(),
        setValueAggregation: () => actions.runAfterChange(),
        setFilterOperator: () => actions.runAfterChange(),
        setFilterValue: () => actions.runAfterChange(),
        updateFilter: () => actions.runAfterChange(),
        setLimit: () => actions.runAfterChange(),
        setSort: () => actions.runAfterChange(),
        setFieldExpression: () => actions.runAfterChange(),
        setFieldDateBucket: () => actions.runAfterChange(),
        setValueCustomExpression: () => actions.runAfterChange(),
        setFilterCustomExpression: () => actions.runAfterChange(),
        resetConfig: () => actions.runAfterChange(),
    })),
    subscriptions(({ actions, values }) => ({
        config: (config: BIConfig, oldConfig: BIConfig | undefined) => {
            if (
                config.source &&
                (config.source.connectionId ?? null) === values.databaseConnectionId &&
                (!oldConfig?.source || getBIDataSourceKey(config.source) !== getBIDataSourceKey(oldConfig.source))
            ) {
                actions.hydrateTableFields([config.source.table])
            }
        },
    })),
])
