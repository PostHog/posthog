import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { isWidgetConfigValidationError } from '../../utils'
import { resolveWidgetFilterTestAccounts } from '../../widget_types/configSchemas'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editErrorTrackingWidgetModalLogicType } from './editErrorTrackingWidgetModalLogicType'
import {
    validateErrorTrackingWidgetConfigInput,
    type ErrorTrackingWidgetFieldErrors,
} from './errorTrackingWidgetConfigValidation'
import { canConfigureErrorTrackingWidgetIssues } from './utils'

export type EditErrorTrackingWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editErrorTrackingWidgetModalLogic = kea<editErrorTrackingWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'error_tracking', 'editErrorTrackingWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditErrorTrackingWidgetModalLogicProps),

    connect({
        values: [
            teamLogic,
            ['currentTeam'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            exceptionIngestionLogic,
            ['hasSentExceptionEvent', 'hasSentExceptionEventLoading'],
        ],
    }),

    actions({
        setLimit: (limit: number) => ({ limit }),
        setOrderBy: (orderBy: string) => ({ orderBy }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
        setTileName: (tileName: string) => ({ tileName }),
        setTileDescription: (tileDescription: string) => ({ tileDescription }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setFieldErrors: (fieldErrors: ErrorTrackingWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof ErrorTrackingWidgetFieldErrors) => ({ field }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        limit: [
            10,
            {
                setLimit: (_, { limit }) => limit,
            },
        ],
        orderBy: [
            'occurrences',
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        dateFrom: [
            '-7d',
            {
                setDateFrom: (_, { dateFrom }) => dateFrom,
            },
        ],
        tileName: [
            '',
            {
                setTileName: (_, { tileName }) => tileName,
            },
        ],
        tileDescription: [
            '',
            {
                setTileDescription: (_, { tileDescription }) => tileDescription,
            },
        ],
        filterTestAccounts: [
            false,
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
            },
        ],
        fieldErrors: [
            {} as ErrorTrackingWidgetFieldErrors,
            {
                setFieldErrors: (_, { fieldErrors }) => fieldErrors,
                clearFieldError: (state, { field }) => {
                    if (!state[field]) {
                        return state
                    }
                    const next = { ...state }
                    delete next[field]
                    return next
                },
            },
        ],
        saving: [
            false,
            {
                submit: () => true,
                submitSuccess: () => false,
                submitFailure: () => false,
            },
        ],
    }),

    selectors({
        showIssueSettings: [
            (s) => [s.currentTeam, s.hasSentExceptionEvent, s.hasSentExceptionEventLoading],
            (currentTeam, hasSentExceptionEvent, hasSentExceptionEventLoading): boolean =>
                canConfigureErrorTrackingWidgetIssues(currentTeam, hasSentExceptionEvent) &&
                !hasSentExceptionEventLoading &&
                !!currentTeam,
        ],
        widgetConfig: [(_, p) => [p.config], (config): Record<string, unknown> => config],
        validation: [
            (s) => [s.limit, s.orderBy, s.dateFrom, s.filterTestAccounts, s.widgetConfig],
            (limit, orderBy, dateFrom, filterTestAccounts, widgetConfig) =>
                validateErrorTrackingWidgetConfigInput({
                    limit,
                    orderBy,
                    dateFrom,
                    filterTestAccounts,
                    baseConfig: widgetConfig,
                }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): ErrorTrackingWidgetFieldErrors => {
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
        defaultTitle: [(_state, props) => props.defaultTitle ?? 'Untitled'],
    }),

    defaults(({ props, values }) => {
        const dateFrom = (props.config.dateRange as { date_from?: string } | undefined)?.date_from ?? '-7d'

        return {
            limit: (props.config.limit as number) ?? 10,
            orderBy: (props.config.orderBy as string) ?? 'occurrences',
            dateFrom,
            tileName: props.name ?? '',
            tileDescription: props.description ?? '',
            filterTestAccounts: resolveWidgetFilterTestAccounts(
                props.config.filterTestAccounts as boolean | undefined,
                values.filterTestAccountsDefault
            ),
            fieldErrors: {},
            saving: false,
        }
    }),

    listeners(({ actions, props, values }) => ({
        submit: async () => {
            const result = validateErrorTrackingWidgetConfigInput({
                limit: values.limit,
                orderBy: values.orderBy,
                dateFrom: values.dateFrom,
                filterTestAccounts: values.filterTestAccounts,
                baseConfig: props.config,
            })

            if (!result.success) {
                actions.setFieldErrors(result.fieldErrors)
                return
            }

            try {
                const trimmedName = values.tileName.trim()
                const trimmedDescription = values.tileDescription.trim()
                const nameChanged = trimmedName !== (props.name ?? '').trim()
                const descriptionChanged = trimmedDescription !== (props.description ?? '').trim()

                await props.onSave(result.config)
                if (props.onSaveMetadata) {
                    const metadata: { name?: string; description?: string } = {}
                    if (nameChanged) {
                        metadata.name = trimmedName === (props.defaultTitle ?? 'Untitled').trim() ? '' : trimmedName
                    }
                    if (descriptionChanged) {
                        metadata.description = trimmedDescription
                    }
                    if (Object.keys(metadata).length > 0) {
                        await props.onSaveMetadata(metadata)
                    }
                }
                actions.setFieldErrors({})
                props.onClose()
                actions.submitSuccess()
            } catch (error) {
                actions.submitFailure()
                if (isWidgetConfigValidationError(error)) {
                    actions.setFieldErrors(error.fieldErrors as ErrorTrackingWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
