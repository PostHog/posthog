import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { uuid } from 'lib/utils/dom'
import { TableFieldsStatus, databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import {
    BIAggregation,
    BIConfig,
    BIDataSource,
    BIDateBucket,
    BIField,
    BIFilter,
    BIFilterOperator,
    BITableCalculation,
    BITopN,
    BITotals,
    BIValue,
    BIQueryLimit,
    BISort,
    BIConditionGroup,
    BIResultFilter,
    BIHierarchy,
} from '~/queries/schema/schema-business-intelligence'
import {
    CompareFilter,
    DatabaseSchemaTable,
    DateRange,
    HogQLMetadata,
    HogQLMetadataResponse,
    HogLanguage,
    NodeKind,
} from '~/queries/schema/schema-general'
import { escapeDottedHogQLIdentifier } from '~/queries/utils'
import { ChartDisplayType } from '~/types'

import {
    captureBIEditorModeSelected,
    captureBIWorksheetAction,
} from 'products/business_intelligence/frontend/biEditorAnalytics'
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
    getBIValueSortKey,
    isBIFieldCompatible,
    isBIMeasureField,
    normalizeBIConfig,
} from 'products/business_intelligence/frontend/biEditorTypes'

import type { BIPaneSettings } from '../../../frontend/src/queries/schema/schema-business-intelligence'
import {
    getBILocalFields,
    inferBICalculatedFieldType,
    localFieldError,
    localFieldExpression,
    upsertBILocalField,
} from './biLocalFields'
import { matchesBIFieldSearch } from './biPropertyFields'
import { getBIDateField } from './biQueryFilters'

export interface BIEditorLogicProps {
    tabId: string
}

export interface BICalculatedMeasureDraft {
    index: number | null
    name: string
    expression: string
    kind?: 'dimension' | 'measure'
    fieldId?: string
    type?: BIField['type']
    typeOverride?: boolean
    shelf?: 'rows' | 'columns'
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
        localFields: undefined,
        hierarchies: undefined,
        colorBy: undefined,
        querySnapshot: undefined,
        catalogMetric: undefined,
        comparisonPeriod: undefined,
        rows: [],
        columns: [],
        values: [],
        filters: [],
        dateField: defaultDateFilter?.field ?? getBIDateField({ ...config, source, dateField: undefined }),
        rowFilterGroup: undefined,
        resultFilters: undefined,
        resultFilterGroup: undefined,
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

function addValueToConfig(config: BIConfig, value: BIValue): BIConfig {
    const preserveCount =
        !config.values.length &&
        (config.resultFilters?.some((filter) => filter.measureIndex === 0) || config.topN?.measureIndex === 0)
    const values: BIValue[] =
        preserveCount && config.source
            ? [
                  {
                      field: blankField(config.source, 'bi-default-count'),
                      aggregation: 'custom',
                      customExpression: 'count(*)',
                      label: 'Count',
                  },
              ]
            : config.values
    return { ...config, values: [...values, value] }
}

function addFieldToConfig(config: BIConfig, field: BIField, shelf: BIShelf): BIConfig {
    if (!isBIFieldCompatible(config.source, field)) {
        return config
    }

    const source = config.source ?? field.source
    const sourceConfig = config.source ? config : setDataSourceInConfig(config, source)

    if (field.localDefinition?.kind === 'expression' && field.localDefinition.aggregate && shelf === 'filters') {
        return config
    }
    switch (shelf) {
        case 'rows':
        case 'columns':
            if (sourceConfig[shelf].some((existingField) => existingField.id === field.id)) {
                return sourceConfig
            }
            return { ...sourceConfig, source, [shelf]: [...sourceConfig[shelf], field] }
        case 'values':
            return addValueToConfig(
                sourceConfig,
                field.localDefinition?.kind === 'expression' && field.localDefinition.aggregate
                    ? { field, aggregation: 'custom', customExpression: field.expression, label: field.name }
                    : { field, aggregation: defaultAggregationForField(field) }
            )
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

function moveFieldInConfig(
    config: BIConfig,
    fromShelf: BIShelf,
    fromIndex: number,
    toShelf: BIShelf,
    toIndex?: number
): BIConfig {
    if (fromShelf === toShelf) {
        const fields = [...config[fromShelf]]
        const target = Math.max(0, Math.min(toIndex ?? fields.length, fields.length))
        const [field] = fields.splice(fromIndex, 1)
        if (!field) {
            return config
        }
        fields.splice(target > fromIndex ? target - 1 : target, 0, field)
        if (fromShelf === 'values') {
            const indices = (fields as BIValue[]).map((value) => config.values.indexOf(value))
            const sortedIndex = config.values.findIndex(
                (_, index) => getBIValueSortKey(config, index) === config.sort?.key
            )
            return {
                ...config,
                values: fields as BIValue[],
                sort:
                    config.sort && sortedIndex !== -1
                        ? {
                              ...config.sort,
                              key:
                                  getBIValueSortKey(
                                      { ...config, values: fields as BIValue[] },
                                      indices.indexOf(sortedIndex)
                                  ) ?? config.sort.key,
                          }
                        : config.sort,
                resultFilters: config.resultFilters?.map((filter) => ({
                    ...filter,
                    measureIndex: indices.indexOf(filter.measureIndex),
                })),
                topN: config.topN
                    ? { ...config.topN, measureIndex: indices.indexOf(config.topN.measureIndex) }
                    : undefined,
            }
        }
        return { ...config, [fromShelf]: fields }
    }
    if (fromShelf === 'values' && (toShelf === 'rows' || toShelf === 'columns')) {
        return {
            ...config,
            values: config.values.map((value, index) => (index === fromIndex ? { ...value, shelf: toShelf } : value)),
        }
    }
    if (fromShelf === 'values' && config.values[fromIndex]?.label) {
        return config
    }
    const field = fieldOnShelf(config, fromShelf, fromIndex)
    if (!field) {
        return config
    }

    const next = addFieldToConfig(removeFieldFromConfig(config, fromShelf, fromIndex), field, toShelf)
    return toIndex === undefined ? next : moveFieldInConfig(next, toShelf, next[toShelf].length - 1, toShelf, toIndex)
}

function removeFieldFromConfig(config: BIConfig, shelf: BIShelf, index: number): BIConfig {
    switch (shelf) {
        case 'rows':
        case 'columns':
            return { ...config, [shelf]: config[shelf].filter((_, fieldIndex) => fieldIndex !== index) }
        case 'values':
            return {
                ...config,
                values: config.values.filter((_, valueIndex) => valueIndex !== index),
                resultFilters: config.resultFilters
                    ?.filter((filter) => filter.measureIndex !== index)
                    .map((filter) => ({
                        ...filter,
                        measureIndex: filter.measureIndex > index ? filter.measureIndex - 1 : filter.measureIndex,
                    })),
                topN:
                    !config.topN || config.topN.measureIndex === index
                        ? undefined
                        : {
                              ...config.topN,
                              measureIndex:
                                  config.topN.measureIndex > index
                                      ? config.topN.measureIndex - 1
                                      : config.topN.measureIndex,
                          },
            }
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
                topN: config.topN?.measureIndex === index ? undefined : config.topN,
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
    dateBucket: BIDateBucket | null,
    datePart?: BIField['datePart']
): BIConfig {
    const updateField = (field: BIField): BIField => ({ ...field, dateBucket: dateBucket ?? undefined, datePart })

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

export type BIPanel = 'charts' | 'analysis' | 'display'

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
    activeMeasureSettingsIndex: number | null
    activePanel: BIPanel | null
    autoUpdate: boolean
    availableDataSources: BIDataSource[]
    calculatedFieldError: string | undefined
    calculatedFieldMetadata: {
        expression: string
        metadata: HogQLMetadataResponse
        sourceKey: string
    } | null
    calculatedFieldMetadataLoading: boolean
    calculatedFieldValidation: 'checking' | 'idle' | 'invalid' | 'valid'
    calculatedMeasureDraft: BICalculatedMeasureDraft | null
    chartFits: Partial<Record<ChartDisplayType, BIChartFit>>
    config: BIConfig
    dataPaneFields: BIDataPaneFields
    dataPaneFieldsError: boolean
    dataPaneFieldsLoading: boolean
    dataPaneSearch: string
    dragSessionId: string
    editorView: BIEditorView
    fieldsPaneOpen: boolean
    filteredDataPaneFields: BIDataPaneFields
    generatedQuery: BIQueryBuildResult | null
    hoveredChartType: ChartDisplayType | null
    localFieldDraft: BIField | null
    selectableDataSources: BIDataSource[]
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
    addResultFilter: () => {
        id: string
    }
    clearActiveDropShelf: (shelf: BIShelf) => {
        shelf: BIShelf
    }
    combineMeasures: () => {
        value: true
    }
    convertMeasureToDimension: (index: number) => {
        index: number
    }
    duplicateField: (
        shelf: Exclude<BIShelf, 'filters'>,
        index: number,
        toShelf?: BIShelf,
        toIndex?: number
    ) => {
        fieldId: string
        index: number
        shelf: 'columns' | 'rows' | 'values'
        toIndex: number | undefined
        toShelf: BIShelf
    }
    editCalculatedField: (
        field?: BIField,
        shelf?: 'columns' | 'rows'
    ) => {
        field: BIField | undefined
        shelf: 'columns' | 'rows' | undefined
    }
    editCalculatedMeasure: (index?: number | null) => {
        index: number | null
    }
    editLocalField: (
        field: BIField,
        kind: 'bins' | 'groups'
    ) => {
        field: BIField
        kind: 'bins' | 'groups'
    }
    editMeasureSettings: (index: number | null) => {
        index: number | null
    }
    loadCalculatedFieldMetadata: (_: void) => void
    loadCalculatedFieldMetadataFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCalculatedFieldMetadataSuccess: (
        calculatedFieldMetadata: {
            expression: string
            metadata: HogQLMetadataResponse
            sourceKey: string
        } | null,
        payload?: void
    ) => {
        calculatedFieldMetadata: {
            expression: string
            metadata: HogQLMetadataResponse
            sourceKey: string
        } | null
        payload?: void
    }
    moveFieldToShelf: (
        fromShelf: BIShelf,
        fromIndex: number,
        toShelf: BIShelf,
        toIndex?: number
    ) => {
        fromIndex: number
        fromShelf: BIShelf
        toIndex: number | undefined
        toShelf: BIShelf
    }
    removeFieldFromShelf: (
        shelf: BIShelf,
        index: number
    ) => {
        index: number
        shelf: BIShelf
    }
    removeHierarchy: (id: string) => {
        id: string
    }
    removeLocalField: (fieldId: string) => {
        fieldId: string
    }
    removeResultFilter: (id: string) => {
        id: string
    }
    renameField: (
        shelf: Exclude<BIShelf, 'filters'>,
        index: number,
        name: string
    ) => {
        index: number
        name: string
        shelf: 'columns' | 'rows' | 'values'
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
    saveLocalField: () => {
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
    setActivePanel: (panel: BIPanel | null) => {
        panel: BIPanel | null
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
    setColorBy: (colorBy: string | null | undefined) => {
        colorBy: string | null | undefined
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
    setFieldDatePart: (
        shelf: BIShelf,
        index: number,
        datePart: BIField['datePart']
    ) => {
        datePart: 'day_of_week' | 'month' | 'quarter' | undefined
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
    setFilterGroup: (
        scope: 'result' | 'row',
        group: BIConditionGroup
    ) => {
        group: BIConditionGroup
        scope: 'result' | 'row'
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
    setLocalFieldDraft: (field: BIField | null) => {
        field: BIField | null
    }
    setMeasureExpression: (
        index: number,
        expression: string,
        aggregation: BIAggregation
    ) => {
        aggregation: BIAggregation
        expression: string
        index: number
    }
    setMeasureShelf: (
        index: number,
        shelf: 'columns' | 'rows'
    ) => {
        index: number
        shelf: 'columns' | 'rows'
    }
    setMissingDates: (missingDates: BIConfig['missingDates']) => {
        missingDates: 'gap' | 'zero' | undefined
    }
    setPanes: (panes: BIConfig['panes']) => {
        panes: BIPaneSettings | undefined
    }
    setSort: (sort: BISort | null) => {
        sort: BISort | null
    }
    setTableCalculation: (
        index: number,
        tableCalculation: BITableCalculation | undefined
    ) => {
        index: number
        tableCalculation: BITableCalculation | undefined
    }
    setTopN: (topN: BITopN | undefined) => {
        topN: BITopN | undefined
    }
    setTotals: (totals: BITotals) => {
        totals: BITotals
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
    startSuggestedChart: () => {
        value: true
    }
    swapRowsAndColumns: () => {
        value: true
    }
    toggleFieldsPane: () => {
        value: true
    }
    updateFilter: (
        index: number,
        update: Partial<Pick<BIFilter, 'enabled' | 'label' | 'value' | 'values' | 'valueTo'>>
    ) => {
        index: number
        update: Partial<Pick<BIFilter, 'enabled' | 'label' | 'value' | 'values' | 'valueTo'>>
    }
    updateMeasureSettings: (
        index: number,
        settings: Pick<BIValue, 'display' | 'formatting'>
    ) => {
        index: number
        settings: Pick<BIValue, 'display' | 'formatting'>
    }
    updateResultFilter: (
        id: string,
        update: Partial<BIResultFilter>
    ) => {
        id: string
        update: Partial<BIResultFilter>
    }
    upsertCalculatedMeasure: (draft: BICalculatedMeasureDraft) => {
        draft: BICalculatedMeasureDraft
        fieldId: string
    }
    upsertHierarchy: (hierarchy: BIHierarchy) => {
        hierarchy: BIHierarchy
    }
    upsertLocalField: (field: BIField) => {
        field: BIField
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface biEditorLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        calculatedFieldValidation: (
            calculatedMeasureDraft: BICalculatedMeasureDraft | null,
            calculatedFieldMetadata: {
                expression: string
                metadata: HogQLMetadataResponse
                sourceKey: string
            } | null,
            calculatedFieldMetadataLoading: boolean,
            config: BIConfig
        ) => 'checking' | 'idle' | 'invalid' | 'valid'
        calculatedFieldError: (
            calculatedMeasureDraft: BICalculatedMeasureDraft | null,
            config: BIConfig
        ) => string | undefined
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
        startSuggestedChart: true,
        renameField: (shelf: Exclude<BIShelf, 'filters'>, index: number, name: string) => ({ shelf, index, name }),
        editLocalField: (field: BIField, kind: 'groups' | 'bins') => ({ field, kind }),
        setLocalFieldDraft: (field: BIField | null) => ({ field }),
        saveLocalField: true,
        upsertLocalField: (field: BIField) => ({ field }),
        upsertHierarchy: (hierarchy: BIHierarchy) => ({ hierarchy }),
        removeHierarchy: (id: string) => ({ id }),
        setFilterGroup: (scope: 'row' | 'result', group: BIConditionGroup) => ({ scope, group }),
        addResultFilter: () => ({ id: uuid() }),
        updateResultFilter: (id: string, update: Partial<BIResultFilter>) => ({ id, update }),
        removeResultFilter: (id: string) => ({ id }),
        setEditorView: (editorView: BIEditorView) => ({ editorView }),
        restoreState: (state: BIEditorState) => ({ state }),
        addFieldToShelf: (field: BIField, shelf: BIShelf) => ({ field, shelf }),
        addBlankFieldToShelf: (shelf: BIShelf) => ({ shelf, fieldId: `bi-blank-${uuid()}` }),
        editCalculatedMeasure: (index: number | null = null) => ({ index }),
        setCalculatedMeasureDraft: (draft: BICalculatedMeasureDraft | null) => ({ draft }),
        saveCalculatedMeasure: true,
        upsertCalculatedMeasure: (draft: BICalculatedMeasureDraft) => ({ draft, fieldId: `bi-calculated-${uuid()}` }),
        clearActiveDropShelf: (shelf: BIShelf) => ({ shelf }),
        moveFieldToShelf: (fromShelf: BIShelf, fromIndex: number, toShelf: BIShelf, toIndex?: number) => ({
            fromShelf,
            fromIndex,
            toShelf,
            toIndex,
        }),
        setMeasureShelf: (index: number, shelf: 'rows' | 'columns') => ({ index, shelf }),
        swapRowsAndColumns: true,
        setColorBy: (colorBy: string | null | undefined) => ({ colorBy }),
        editCalculatedField: (field?: BIField, shelf?: 'rows' | 'columns') => ({ field, shelf }),
        removeLocalField: (fieldId: string) => ({ fieldId }),
        duplicateField: (
            shelf: Exclude<BIShelf, 'filters'>,
            index: number,
            toShelf: BIShelf = shelf,
            toIndex?: number
        ) => ({ shelf, index, toShelf, toIndex, fieldId: uuid() }),
        setFieldDatePart: (shelf: BIShelf, index: number, datePart: BIField['datePart']) => ({
            shelf,
            index,
            datePart,
        }),
        convertMeasureToDimension: (index: number) => ({ index }),
        setAutoUpdate: (autoUpdate: boolean) => ({ autoUpdate }),
        setActivePanel: (panel: BIPanel | null) => ({ panel }),
        toggleFieldsPane: true,
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
        setMissingDates: (missingDates: BIConfig['missingDates']) => ({ missingDates }),
        setDateField: (field: BIField | null) => ({ field }),
        setDataSource: (source: BIDataSource) => ({ source }),
        setValueAggregation: (index: number, aggregation: BIAggregation) => ({ index, aggregation }),
        setTableCalculation: (index: number, tableCalculation: BITableCalculation | undefined) => ({
            index,
            tableCalculation,
        }),
        setTopN: (topN: BITopN | undefined) => ({ topN }),
        setTotals: (totals: BITotals) => ({ totals }),
        editMeasureSettings: (index: number | null) => ({ index }),
        updateMeasureSettings: (index: number, settings: Pick<BIValue, 'formatting' | 'display'>) => ({
            index,
            settings,
        }),
        combineMeasures: true,
        setFilterOperator: (index: number, operator: BIFilterOperator) => ({ index, operator }),
        setFilterValue: (index: number, value: string) => ({ index, value }),
        updateFilter: (
            index: number,
            update: Partial<Pick<BIFilter, 'value' | 'values' | 'valueTo' | 'enabled' | 'label'>>
        ) => ({
            index,
            update,
        }),
        setLimit: (limit: BIQueryLimit) => ({ limit }),
        setPanes: (panes: BIConfig['panes']) => ({ panes }),
        setSort: (sort: BISort | null) => ({ sort }),
        setFieldExpression: (shelf: BIShelf, index: number, expression: string) => ({ shelf, index, expression }),
        setFieldDateBucket: (shelf: BIShelf, index: number, dateBucket: BIDateBucket | null) => ({
            shelf,
            index,
            dateBucket,
        }),
        setValueCustomExpression: (index: number, customExpression: string) => ({ index, customExpression }),
        setMeasureExpression: (index: number, expression: string, aggregation: BIAggregation) => ({
            index,
            expression,
            aggregation,
        }),
        setFilterCustomExpression: (index: number, customExpression: string) => ({ index, customExpression }),
        resetConfig: true,
    }),
    loaders(({ values }) => ({
        calculatedFieldMetadata: [
            null as { expression: string; sourceKey: string; metadata: HogQLMetadataResponse } | null,
            {
                loadCalculatedFieldMetadata: async (_: void, breakpoint) => {
                    const draft = values.calculatedMeasureDraft
                    const source = values.config.source
                    if (!draft?.expression.trim() || !source) {
                        return null
                    }
                    const cached = values.calculatedFieldMetadata
                    if (cached?.expression === draft.expression && cached.sourceKey === getBIDataSourceKey(source)) {
                        return cached
                    }
                    await breakpoint(300)
                    const metadata = await performQuery<HogQLMetadata>({
                        kind: NodeKind.HogQLMetadata,
                        language: HogLanguage.hogQL,
                        query: `SELECT (${draft.expression}) AS value FROM ${escapeDottedHogQLIdentifier(source.table)}`,
                        connectionId: source.connectionId,
                        includeOutputTypes: true,
                    }).catch(
                        (): HogQLMetadataResponse => ({
                            isValid: false,
                            errors: [{ message: 'Could not check SQL. Edit the expression to try again.' }],
                            warnings: [],
                            notices: [],
                        })
                    )
                    breakpoint()
                    return { expression: draft.expression, sourceKey: getBIDataSourceKey(source), metadata }
                },
            },
        ],
    })),
    reducers({
        localFieldDraft: [
            null as BIField | null,
            { setLocalFieldDraft: (_, { field }) => field, upsertLocalField: () => null, setDataSource: () => null },
        ],
        activeMeasureSettingsIndex: [null as number | null, { editMeasureSettings: (_, { index }) => index }],
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
        autoUpdate: [false, { persist: true }, { setAutoUpdate: (_, { autoUpdate }) => autoUpdate }],
        activePanel: [null as BIPanel | null, { setActivePanel: (_, { panel }) => panel }],
        fieldsPaneOpen: [true, { toggleFieldsPane: (open) => !open }],
        hoveredChartType: [
            null as ChartDisplayType | null,
            { setHoveredChartType: (_, { chartType }) => chartType, setActivePanel: () => null },
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
                renameField: (config, { shelf, index, name }) => {
                    if (!name.trim()) {
                        return config
                    }
                    return shelf === 'values'
                        ? {
                              ...config,
                              values: config.values.map((value, i) =>
                                  i === index ? { ...value, display: { ...value.display, label: name.trim() } } : value
                              ),
                          }
                        : {
                              ...config,
                              [shelf]: config[shelf].map((field, i) =>
                                  i === index ? { ...field, label: name.trim() } : field
                              ),
                          }
                },
                upsertLocalField: (config, { field }) => upsertBILocalField(config, field),
                upsertHierarchy: (config, { hierarchy }) => ({
                    ...config,
                    hierarchies: [...(config.hierarchies ?? []).filter((item) => item.id !== hierarchy.id), hierarchy],
                }),
                removeHierarchy: (config, { id }) => ({
                    ...config,
                    hierarchies: config.hierarchies?.filter((item) => item.id !== id),
                }),
                upsertCalculatedMeasure: (config, { draft, fieldId }) => {
                    if (!config.source) {
                        return config
                    }
                    const existing = draft.index === null ? null : config.values[draft.index]
                    const id =
                        draft.fieldId ?? existing?.field.localFieldId ?? (existing?.label ? existing.field.id : fieldId)
                    const aggregate = draft.kind !== 'dimension'
                    const field: BIField = {
                        ...blankField(config.source, id),
                        name: draft.name.trim(),
                        expression: draft.expression.trim(),
                        type: draft.type ?? (aggregate ? 'float' : 'string'),
                        localDefinition: { kind: 'expression', expression: draft.expression.trim(), aggregate },
                    }
                    const updated = upsertBILocalField({ ...config, localFields: getBILocalFields(config) }, field)
                    if (existing && existing.field.id !== id && !existing.field.localFieldId) {
                        return {
                            ...updated,
                            values: updated.values.map((value, index) =>
                                index === draft.index
                                    ? {
                                          ...value,
                                          field,
                                          aggregation: 'custom',
                                          customExpression: field.expression,
                                          label: field.name,
                                      }
                                    : value
                            ),
                        }
                    }
                    if (draft.fieldId || existing) {
                        return updated
                    }
                    return aggregate
                        ? addValueToConfig(updated, {
                              field,
                              aggregation: 'custom',
                              customExpression: field.expression,
                              label: field.name,
                              shelf: draft.shelf,
                          })
                        : addFieldToConfig(updated, field, draft.shelf ?? 'rows')
                },
                removeLocalField: (config, { fieldId }) => {
                    const matches = (field: BIField): boolean => (field.localFieldId ?? field.id) === fieldId
                    let next = {
                        ...config,
                        localFields: getBILocalFields(config).filter((field) => field.id !== fieldId),
                    }
                    for (let index = next.values.length - 1; index >= 0; index--) {
                        if (matches(next.values[index].field)) {
                            next = { ...removeFieldFromConfig(next, 'values', index), localFields: next.localFields }
                        }
                    }
                    return normalizeBIConfig({
                        ...next,
                        rows: next.rows.filter((field) => !matches(field)),
                        columns: next.columns.filter((field) => !matches(field)),
                        hierarchies: next.hierarchies
                            ?.map((hierarchy) => ({
                                ...hierarchy,
                                levels: hierarchy.levels.filter((field) => !matches(field)),
                            }))
                            .filter((hierarchy) => hierarchy.levels.length >= 2),
                        filters: next.filters.filter((filter) => !matches(filter.field)),
                        dateField: next.dateField && matches(next.dateField) ? undefined : next.dateField,
                    })
                },
                addFieldToShelf: (config, { field, shelf }) => addFieldToConfig(config, field, shelf),
                setFilterGroup: (config, { scope, group }) => ({
                    ...config,
                    [scope === 'row' ? 'rowFilterGroup' : 'resultFilterGroup']: group,
                }),
                addResultFilter: (config, { id }) => ({
                    ...config,
                    resultFilters: [
                        ...(config.resultFilters ?? []),
                        { id, measureIndex: 0, operator: 'greater_than', value: '' },
                    ],
                }),
                updateResultFilter: (config, { id, update }) => ({
                    ...config,
                    resultFilters: config.resultFilters?.map((filter) =>
                        filter.id === id ? { ...filter, ...update, id } : filter
                    ),
                }),
                removeResultFilter: (config, { id }) => ({
                    ...config,
                    resultFilters: config.resultFilters?.filter((filter) => filter.id !== id),
                }),
                addBlankFieldToShelf: (config, { shelf, fieldId }) =>
                    config.source ? addFieldToConfig(config, blankField(config.source, fieldId), shelf) : config,
                removeFieldFromShelf: (config, { shelf, index }) => removeFieldFromConfig(config, shelf, index),
                moveFieldToShelf: (config, { fromShelf, fromIndex, toShelf, toIndex }) =>
                    normalizeBIConfig(moveFieldInConfig(config, fromShelf, fromIndex, toShelf, toIndex)),
                setMeasureShelf: (config, { index, shelf }) => ({
                    ...config,
                    values: config.values.map((value, i) => (i === index ? { ...value, shelf } : value)),
                }),
                convertMeasureToDimension: (config, { index }) => {
                    const value = config.values[index]
                    if (!value || (value.aggregation === 'custom' && value.label)) {
                        return config
                    }
                    return normalizeBIConfig(
                        addFieldToConfig(
                            removeFieldFromConfig(config, 'values', index),
                            value.field,
                            value.shelf ?? 'rows'
                        )
                    )
                },
                swapRowsAndColumns: (config) =>
                    normalizeBIConfig({
                        ...config,
                        rows: config.columns,
                        columns: config.rows,
                        values: (config.values.length
                            ? config.values
                            : config.source && (config.rows.length || config.columns.length)
                              ? [
                                    {
                                        field: blankField(config.source, 'bi-default-count'),
                                        aggregation: 'custom' as const,
                                        customExpression: 'count(*)',
                                        label: 'Count of rows',
                                    },
                                ]
                              : []
                        ).map((value: BIValue) => ({
                            ...value,
                            shelf: value.shelf === 'columns' ? 'rows' : 'columns',
                        })),
                        sort: config.sort
                            ? {
                                  ...config.sort,
                                  key: (config.sort.key === 'values:count' && !config.values.length
                                      ? 'values:bi-default-count'
                                      : config.sort.key
                                  ).replace(
                                      /^(rows|columns):/,
                                      (_, shelf) => `${shelf === 'rows' ? 'columns' : 'rows'}:`
                                  ),
                              }
                            : config.sort,
                        chartType:
                            config.chartType === ChartDisplayType.ActionsBar
                                ? ChartDisplayType.ActionsBarValue
                                : config.chartType === ChartDisplayType.ActionsBarValue
                                  ? ChartDisplayType.ActionsBar
                                  : config.chartType,
                    }),
                setChartType: (config, { chartType }) => normalizeBIConfig({ ...config, chartType }),
                setColorBy: (config, { colorBy }) => normalizeBIConfig({ ...config, colorBy }),
                setDateRange: (config, { dateRange }) => ({ ...config, dateRange }),
                setCompareFilter: (config, { compareFilter }) => ({ ...config, compareFilter }),
                setMissingDates: (config, { missingDates }) => ({ ...config, missingDates }),
                setDateField: (config, { field }) => ({ ...config, dateField: field }),
                setDataSource: (config, { source }) => setDataSourceInConfig(config, source),
                setValueAggregation: (config, { index, aggregation }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index ? { ...value, aggregation } : value
                    ),
                }),
                setTableCalculation: (config, { index, tableCalculation }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index
                            ? {
                                  ...value,
                                  ...(!value.formatting &&
                                  ['percent_of_total', 'percent_change'].includes(value.tableCalculation?.type ?? '') &&
                                  !['percent_of_total', 'percent_change'].includes(tableCalculation?.type ?? '')
                                      ? { formatting: { style: 'number' as const, prefix: '', suffix: '' } }
                                      : {}),
                                  tableCalculation,
                              }
                            : value
                    ),
                }),
                setTopN: (config, { topN }) => ({ ...config, topN }),
                setTotals: (config, { totals }) => ({ ...config, totals }),
                updateMeasureSettings: (config, { index, settings }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index ? { ...value, ...settings } : value
                    ),
                }),
                combineMeasures: (config) =>
                    config.values.length === 2
                        ? {
                              ...config,
                              chartType: ChartDisplayType.ActionsBar,
                              values: config.values.map((value, index) => ({
                                  ...value,
                                  display: {
                                      ...value.display,
                                      displayType: index === 0 ? ('bar' as const) : ('line' as const),
                                      yAxisPosition: index === 0 ? ('left' as const) : ('right' as const),
                                  },
                              })),
                          }
                        : config,
                setFilterOperator: (config, { index, operator }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? changeBIFilterOperator(filter, operator) : filter
                    ),
                }),
                setFilterValue: (config, { index, value }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, value, values: undefined } : filter
                    ),
                }),
                updateFilter: (config, { index, update }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, ...update } : filter
                    ),
                }),
                setLimit: (config, { limit }) => normalizeBIConfig({ ...config, limit }),
                setPanes: (config, { panes }) => normalizeBIConfig({ ...config, panes }),
                setSort: (config, { sort }) => normalizeBIConfig({ ...config, sort }),
                setFieldExpression: (config, { shelf, index, expression }) =>
                    setFieldExpressionInConfig(config, shelf, index, expression),
                setFieldDateBucket: (config, { shelf, index, dateBucket }) =>
                    setFieldDateBucketInConfig(config, shelf, index, dateBucket),
                setFieldDatePart: (config, { shelf, index, datePart }) =>
                    setFieldDateBucketInConfig(config, shelf, index, null, datePart),
                duplicateField: (config, { shelf, index, fieldId, toShelf, toIndex }) => {
                    let duplicated: BIConfig
                    if (shelf === 'values') {
                        const value = config.values[index]
                        if (!value || (toShelf === 'filters' && value.label)) {
                            return config
                        }
                        duplicated = {
                            ...config,
                            values: [
                                ...config.values,
                                {
                                    ...value,
                                    shelf:
                                        toShelf === 'values' && toIndex !== undefined
                                            ? (config.values[toIndex]?.shelf ?? value.shelf)
                                            : value.shelf,
                                },
                            ],
                        }
                    } else {
                        const field = config[shelf][index]
                        if (!field) {
                            return config
                        }
                        duplicated = {
                            ...config,
                            [shelf]: [
                                ...config[shelf],
                                {
                                    ...field,
                                    id: fieldId,
                                    localFieldId: field.localDefinition ? (field.localFieldId ?? field.id) : undefined,
                                },
                            ],
                        }
                    }
                    return moveFieldInConfig(duplicated, shelf, config[shelf].length, toShelf, toIndex)
                },
                setValueCustomExpression: (config, { index, customExpression }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index ? { ...value, customExpression } : value
                    ),
                }),
                setMeasureExpression: (config, { index, expression, aggregation }) => ({
                    ...config,
                    values: config.values.map((value, valueIndex) =>
                        valueIndex === index
                            ? {
                                  ...value,
                                  aggregation,
                                  ...(aggregation === 'custom'
                                      ? { customExpression: expression }
                                      : { field: { ...value.field, expression, name: expression.trim() } }),
                              }
                            : value
                    ),
                    topN: config.topN?.measureIndex === index ? undefined : config.topN,
                }),
                setFilterCustomExpression: (config, { index, customExpression }) => ({
                    ...config,
                    filters: config.filters.map((filter, filterIndex) =>
                        filterIndex === index ? { ...filter, customExpression } : filter
                    ),
                }),
                restoreState: (_, { state }) => normalizeBIConfig(state.config),
                resetConfig: (config) => ({
                    ...freshBIConfig(),
                    source: config.source,
                    localFields: getBILocalFields(config),
                    hierarchies: config.hierarchies,
                    memberAliases: config.memberAliases,
                    dateField: config.dateField,
                    dateRange: config.dateRange,
                }),
            },
        ],
    }),
    selectors({
        calculatedFieldValidation: [
            (s) => [s.calculatedMeasureDraft, s.calculatedFieldMetadata, s.calculatedFieldMetadataLoading, s.config],
            (
                draft: BICalculatedMeasureDraft | null,
                result: { expression: string; sourceKey: string; metadata: HogQLMetadataResponse } | null,
                loading: boolean,
                config: BIConfig
            ): 'idle' | 'checking' | 'valid' | 'invalid' => {
                if (!draft?.expression.trim()) {
                    return 'idle'
                }
                if (
                    loading ||
                    result?.expression !== draft.expression ||
                    (config.source && result.sourceKey !== getBIDataSourceKey(config.source))
                ) {
                    return 'checking'
                }
                return result.metadata.isValid ? 'valid' : 'invalid'
            },
        ],
        calculatedFieldError: [
            (s) => [s.calculatedMeasureDraft, s.config],
            (draft: BICalculatedMeasureDraft | null, config: BIConfig): string | undefined => {
                if (!draft?.name.trim()) {
                    return 'Enter a name for this field'
                }
                if (!draft.expression.trim()) {
                    return 'Enter a HogQL expression'
                }
                const existingId =
                    draft.fieldId ??
                    (draft.index === null
                        ? undefined
                        : (config.values[draft.index]?.field.localFieldId ?? config.values[draft.index]?.field.id))
                if (
                    getBILocalFields(config).some(
                        (field) =>
                            field.id !== existingId && field.name.toLowerCase() === draft.name.trim().toLowerCase()
                    )
                ) {
                    return 'A local field with this name already exists'
                }
            },
        ],
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
            (config: BIConfig): BIQueryBuildResult | null =>
                config.querySnapshot || config.rows.length || config.columns.length || config.values.length
                    ? buildBIQuery(config)
                    : null,
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
                    ? {
                          ...getBIDataPaneFields(
                              allTables.find((table) => table.name === config.source?.table),
                              config.source
                          ),
                          measures: [
                              ...getBILocalFields(config).filter(isBIMeasureField),
                              ...getBIDataPaneFields(
                                  allTables.find((table) => table.name === config.source?.table),
                                  config.source
                              ).measures,
                          ],
                          dimensions: [
                              ...getBILocalFields(config).filter((field) => !isBIMeasureField(field)),
                              ...getBIDataPaneFields(
                                  allTables.find((table) => table.name === config.source?.table),
                                  config.source
                              ).dimensions,
                          ],
                      }
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
        editLocalField: ({ field, kind }) =>
            actions.setLocalFieldDraft(
                field.localDefinition
                    ? field
                    : {
                          ...field,
                          id: `bi-local-${uuid()}`,
                          name: `${field.name} ${kind}`,
                          type: kind === 'bins' ? 'float' : 'string',
                          dateBucket: undefined,
                          localDefinition:
                              kind === 'bins'
                                  ? { kind, expression: field.expression, width: 10, origin: 0 }
                                  : {
                                        kind,
                                        expression: field.expression,
                                        groups: [{ name: '', values: [] }],
                                        other: 'Other',
                                    },
                      }
            ),
        saveLocalField: () => {
            const draft = values.localFieldDraft
            if (draft?.name.trim() && draft.localDefinition && !localFieldError(draft.localDefinition)) {
                actions.upsertLocalField({ ...draft, expression: localFieldExpression(draft.localDefinition) })
            }
        },
        upsertLocalField: () => {
            captureBIWorksheetAction('local_field_saved', values.config)
            actions.runAfterChange()
        },
        startSuggestedChart: () => {
            const config = values.config
            if (!config.source || config.rows.length || config.columns.length || config.values.length) {
                return
            }
            const dateField = values.dataPaneFields.dimensions.find((field) =>
                ['date', 'datetime'].includes(field.type)
            )
            actions.restoreState({
                editorView: values.editorView,
                config: {
                    ...config,
                    columns: dateField ? [{ ...dateField, dateBucket: 'day' }] : [],
                    values: [
                        {
                            field: blankField(config.source, 'bi-default-count'),
                            aggregation: 'custom',
                            customExpression: 'count(*)',
                            label: 'Count of rows',
                            shelf: 'rows',
                        },
                    ],
                    chartType: dateField ? ChartDisplayType.ActionsLineGraph : ChartDisplayType.BoldNumber,
                },
            })
            actions.runAfterChange()
        },
        renameField: () => actions.runAfterChange(),
        loadCalculatedFieldMetadataSuccess: ({ calculatedFieldMetadata: result }) => {
            const draft = values.calculatedMeasureDraft
            const source = values.config.source
            const type = inferBICalculatedFieldType(result?.metadata.output_columns?.[0]?.type)
            if (
                draft &&
                source &&
                result?.expression === draft.expression &&
                result.sourceKey === getBIDataSourceKey(source) &&
                result.metadata.isValid &&
                type &&
                !draft.typeOverride
            ) {
                actions.setCalculatedMeasureDraft({ ...draft, type })
            }
        },
        setCalculatedMeasureDraft: () => {
            if (
                !values.calculatedMeasureDraft ||
                values.calculatedFieldMetadataLoading ||
                values.calculatedMeasureDraft.expression !== values.calculatedFieldMetadata?.expression ||
                (values.config.source &&
                    values.calculatedFieldMetadata?.sourceKey !== getBIDataSourceKey(values.config.source))
            ) {
                actions.loadCalculatedFieldMetadata()
            }
        },
        editCalculatedField: ({ field, shelf }) => {
            if (!values.config.source) {
                return
            }
            actions.setCalculatedMeasureDraft({
                index: null,
                fieldId: field?.id,
                kind:
                    field?.localDefinition?.kind === 'expression' && field.localDefinition.aggregate
                        ? 'measure'
                        : 'dimension',
                name: field?.name ?? '',
                expression: field?.expression ?? '',
                type: field?.type ?? 'string',
                typeOverride: !!field,
                shelf,
            })
        },
        removeLocalField: () => actions.runAfterChange(),
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
                kind: 'measure',
                fieldId: value?.field.localFieldId,
                type: value?.field.type ?? 'float',
                typeOverride: index !== null,
            })
        },
        saveCalculatedMeasure: () => {
            const draft = values.calculatedMeasureDraft
            if (draft && !values.calculatedFieldError && values.calculatedFieldValidation === 'valid') {
                actions.upsertCalculatedMeasure(draft)
            }
        },
        upsertCalculatedMeasure: () => {
            captureBIWorksheetAction('calculated_field_saved', values.config)
            actions.runAfterChange()
        },
        setFilterGroup: () => actions.runAfterChange(),
        addResultFilter: () => actions.runAfterChange(),
        updateResultFilter: () => actions.runAfterChange(),
        removeResultFilter: () => actions.runAfterChange(),
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
        convertMeasureToDimension: () => actions.runAfterChange(),
        setMeasureShelf: () => actions.runAfterChange(),
        swapRowsAndColumns: () => actions.runAfterChange(),
        setAutoUpdate: ({ autoUpdate }) => {
            if (autoUpdate) {
                actions.runAfterChange()
            }
        },
        addBlankFieldToShelf: () => actions.runAfterChange(),
        removeFieldFromShelf: () => actions.runAfterChange(),
        setChartType: () => actions.runAfterChange(),
        setColorBy: () => actions.runAfterChange(),
        setDateRange: () => actions.runAfterChange(),
        setCompareFilter: () => actions.runAfterChange(),
        setMissingDates: () => actions.runAfterChange(),
        setDateField: () => actions.runAfterChange(),
        upsertHierarchy: () => actions.runAfterChange(),
        removeHierarchy: () => actions.runAfterChange(),
        setDataSource: () => {
            captureBIWorksheetAction('source_selected', values.config, {
                source_certification:
                    values.allTables.find((table) => table.name === values.config.source?.table)?.certification
                        ?.status ?? 'unmarked',
            })
            actions.runAfterChange()
        },
        setValueAggregation: () => actions.runAfterChange(),
        setTableCalculation: () => actions.runAfterChange(),
        setTopN: () => actions.runAfterChange(),
        setTotals: () => actions.runAfterChange(),
        updateMeasureSettings: () => actions.runAfterChange(),
        combineMeasures: () => actions.runAfterChange(),
        setFilterOperator: () => actions.runAfterChange(),
        setFilterValue: () => actions.runAfterChange(),
        updateFilter: () => actions.runAfterChange(),
        setLimit: () => actions.runAfterChange(),
        setPanes: () => actions.runAfterChange(),
        setSort: () => actions.runAfterChange(),
        setFieldExpression: () => actions.runAfterChange(),
        setFieldDateBucket: () => actions.runAfterChange(),
        setFieldDatePart: () => actions.runAfterChange(),
        duplicateField: () => actions.runAfterChange(),
        setValueCustomExpression: () => actions.runAfterChange(),
        setMeasureExpression: () => {
            captureBIWorksheetAction('measure_expression_updated', values.config)
            actions.runAfterChange()
        },
        setFilterCustomExpression: () => actions.runAfterChange(),
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
