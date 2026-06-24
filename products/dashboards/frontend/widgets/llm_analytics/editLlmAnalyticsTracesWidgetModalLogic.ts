import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { dataTableSavedFiltersLogic } from '~/queries/nodes/DataTable/dataTableSavedFiltersLogic'
import { NodeKind, type DataTableNode } from '~/queries/schema/schema-general'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import type { LlmAnalyticsTracesWidgetConfig } from '../../generated/widget-configs.zod'
import { isWidgetConfigValidationError } from '../../utils'
import { resolveWidgetFilterTestAccounts, type WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import {
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
    widgetEditModalFilterTestAccountsActions,
    widgetEditModalFilterTestAccountsReducers,
    widgetEditModalListFieldActions,
    widgetEditModalPropSelectors,
    widgetEditModalSavingReducers,
    widgetEditModalTileActions,
    widgetEditModalTileReducers,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editLlmAnalyticsTracesWidgetModalLogicType } from './editLlmAnalyticsTracesWidgetModalLogicType'
import {
    LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM,
    extractSavedFilterValues,
    parseLlmAnalyticsTracesWidgetConfig,
    validateLlmAnalyticsTracesWidgetConfigInput,
    type LlmAnalyticsTracesWidgetFieldErrors,
} from './llmAnalyticsTracesWidgetConfigValidation'

// AIO Traces saved filters share this storage key (see AIObservabilityTracesScene).
export const LLM_ANALYTICS_TRACES_SAVED_FILTERS_KEY = 'llm-analytics-traces'

// We mount dataTableSavedFiltersLogic only to read its persisted `savedFilters`; query/setQuery
// are never exercised here (no `saved_filter_id` in a dashboard URL), so a minimal valid node is enough.
const SAVED_FILTERS_READ_ONLY_QUERY: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.TracesQuery },
    columns: [],
}

export type EditLlmAnalyticsTracesWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editLlmAnalyticsTracesWidgetModalLogic = kea<editLlmAnalyticsTracesWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'llm_analytics', 'editLlmAnalyticsTracesWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditLlmAnalyticsTracesWidgetModalLogicProps),

    connect(() => ({
        values: [
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            dataTableSavedFiltersLogic({
                uniqueKey: LLM_ANALYTICS_TRACES_SAVED_FILTERS_KEY,
                query: SAVED_FILTERS_READ_ONLY_QUERY,
                setQuery: () => {},
            }),
            ['savedFilters'],
        ],
    })),

    actions({
        ...widgetEditModalListFieldActions,
        ...widgetEditModalTileActions,
        ...widgetEditModalFilterTestAccountsActions,
        setFilterSupportTraces: (filterSupportTraces: boolean) => ({ filterSupportTraces }),
        setDateFrom: (dateFrom: WidgetDateFromValue) => ({ dateFrom }),
        applySavedFilter: (savedFilterId: string) => ({ savedFilterId }),
        setFieldErrors: (fieldErrors: LlmAnalyticsTracesWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof LlmAnalyticsTracesWidgetFieldErrors) => ({ field }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        limit: [
            10,
            {
                setLimit: (_: number, { limit }: { limit: number }) => limit,
            },
        ],
        // Typed here (not via widgetEditModalListFieldReducers) so the value stays a WidgetDateFromValue
        // for the validation call rather than a bare string.
        dateFrom: [
            LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM as WidgetDateFromValue,
            {
                setDateFrom: (_: WidgetDateFromValue, { dateFrom }: { dateFrom: WidgetDateFromValue }) => dateFrom,
            },
        ],
        ...widgetEditModalTileReducers,
        ...widgetEditModalFilterTestAccountsReducers,
        filterSupportTraces: [
            false,
            {
                setFilterSupportTraces: (_: boolean, { filterSupportTraces }: { filterSupportTraces: boolean }) =>
                    filterSupportTraces,
            },
        ],
        appliedSavedFilterId: [
            null as string | null,
            {
                applySavedFilter: (_: string | null, { savedFilterId }: { savedFilterId: string }) => savedFilterId,
            },
        ],
        fieldErrors: [
            {} as LlmAnalyticsTracesWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: LlmAnalyticsTracesWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: LlmAnalyticsTracesWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: LlmAnalyticsTracesWidgetFieldErrors,
                    { field }: { field: keyof LlmAnalyticsTracesWidgetFieldErrors }
                ) => {
                    if (!state[field]) {
                        return state
                    }
                    const next = { ...state }
                    delete next[field]
                    return next
                },
            },
        ],
        ...widgetEditModalSavingReducers,
    }),

    selectors({
        widgetConfig: [
            (_, p) => [p.config],
            (config): LlmAnalyticsTracesWidgetConfig => parseLlmAnalyticsTracesWidgetConfig(config),
        ],
        ...widgetEditModalPropSelectors,
        savedFilterOptions: [
            (s) => [s.savedFilters],
            (savedFilters): { value: string; label: string }[] =>
                (savedFilters ?? []).map((filter) => ({ value: filter.id, label: filter.name })),
        ],
        validation: [
            (s) => [s.limit, s.filterTestAccounts, s.filterSupportTraces, s.dateFrom, s.widgetConfig],
            (limit, filterTestAccounts, filterSupportTraces, dateFrom, widgetConfig) =>
                validateLlmAnalyticsTracesWidgetConfigInput({
                    limit,
                    filterTestAccounts,
                    filterSupportTraces,
                    dateFrom,
                    baseConfig: widgetConfig,
                }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): LlmAnalyticsTracesWidgetFieldErrors => {
                if (!validation.success) {
                    return { ...validation.fieldErrors, ...fieldErrors }
                }
                return fieldErrors
            },
        ],
        saveDisabledReason: [
            (s) => [s.saving, s.validation],
            (saving, validation): string | undefined => {
                if (saving) {
                    return 'Saving…'
                }
                if (!validation.success) {
                    return 'Fix validation errors to save'
                }
                return undefined
            },
        ],
    }),

    defaults(({ props, values }) => {
        const baseConfig = parseLlmAnalyticsTracesWidgetConfig(props.config)

        return {
            limit: baseConfig.limit,
            dateFrom: (baseConfig.dateRange?.date_from ?? LLM_ANALYTICS_TRACES_DEFAULT_DATE_FROM) as WidgetDateFromValue,
            ...getWidgetEditModalTileDefaults(props),
            filterTestAccounts: resolveWidgetFilterTestAccounts(
                baseConfig.filterTestAccounts,
                values.filterTestAccountsDefault
            ),
            filterSupportTraces: baseConfig.filterSupportTraces ?? false,
            appliedSavedFilterId: null,
            fieldErrors: {},
            saving: false,
        }
    }),

    listeners(({ actions, props, values }) => ({
        applySavedFilter: ({ savedFilterId }) => {
            const savedFilter = (values.savedFilters ?? []).find((filter) => filter.id === savedFilterId)
            if (!savedFilter) {
                return
            }
            const source = (savedFilter.query as { source?: Record<string, unknown> } | undefined)?.source
            const extracted = extractSavedFilterValues(source)
            actions.setDateFrom(extracted.dateFrom)
            if (extracted.filterTestAccounts !== null) {
                actions.setFilterTestAccounts(extracted.filterTestAccounts)
            }
            if (extracted.filterSupportTraces !== null) {
                actions.setFilterSupportTraces(extracted.filterSupportTraces)
            }
        },

        submit: async () => {
            const result = values.validation

            if (!result.success) {
                actions.setFieldErrors(result.fieldErrors)
                return
            }

            try {
                await props.onSave(
                    result.config,
                    buildWidgetTileMetadataPatch(props, values.tileName, values.tileDescription)
                )
                actions.setFieldErrors({})
                props.onClose()
                actions.submitSuccess()
            } catch (error) {
                actions.submitFailure()
                if (isWidgetConfigValidationError(error)) {
                    actions.setFieldErrors(error.fieldErrors as LlmAnalyticsTracesWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
