import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import type { ErrorTrackingWidgetConfig } from '../../generated/widget-configs.zod'
import { isWidgetConfigValidationError } from '../../utils'
import { resolveWidgetFilterTestAccounts } from '../../widget_types/widgetConfigShared'
import {
    widgetEditModalFilterTestAccountsActions,
    widgetEditModalListFieldActions,
    widgetEditModalPropSelectors,
    widgetEditModalTileActions,
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editErrorTrackingWidgetModalLogicType } from './editErrorTrackingWidgetModalLogicType'
import {
    parseErrorTrackingWidgetConfig,
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

    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            filterTestAccountsDefaultsLogic,
            ['filterTestAccountsDefault'],
            exceptionIngestionLogic,
            ['hasSentExceptionEvent', 'hasSentExceptionEventLoading'],
        ],
    })),

    actions({
        setOrderBy: (orderBy: string) => ({ orderBy }),
        setOrderDirection: (orderDirection: ErrorTrackingWidgetConfig['orderDirection']) => ({ orderDirection }),
        ...widgetEditModalListFieldActions,
        ...widgetEditModalTileActions,
        ...widgetEditModalFilterTestAccountsActions,
        setFieldErrors: (fieldErrors: ErrorTrackingWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof ErrorTrackingWidgetFieldErrors) => ({ field }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        orderBy: [
            'occurrences' as ErrorTrackingWidgetConfig['orderBy'],
            {
                setOrderBy: (
                    _: ErrorTrackingWidgetConfig['orderBy'],
                    { orderBy }: { orderBy: string }
                ): ErrorTrackingWidgetConfig['orderBy'] => orderBy as ErrorTrackingWidgetConfig['orderBy'],
            },
        ],
        orderDirection: [
            'DESC' as ErrorTrackingWidgetConfig['orderDirection'],
            {
                setOrderDirection: (
                    _: ErrorTrackingWidgetConfig['orderDirection'],
                    { orderDirection }: { orderDirection: ErrorTrackingWidgetConfig['orderDirection'] }
                ): ErrorTrackingWidgetConfig['orderDirection'] => orderDirection,
            },
        ],
        limit: [
            10,
            {
                setLimit: (_: number, { limit }: { limit: number }) => limit,
            },
        ],
        tileName: [
            '',
            {
                setTileName: (_: string, { tileName }: { tileName: string }) => tileName,
            },
        ],
        tileDescription: [
            '',
            {
                setTileDescription: (_: string, { tileDescription }: { tileDescription: string }) => tileDescription,
            },
        ],
        filterTestAccounts: [
            false,
            {
                setFilterTestAccounts: (_: boolean, { filterTestAccounts }: { filterTestAccounts: boolean }) =>
                    filterTestAccounts,
            },
        ],
        fieldErrors: [
            {} as ErrorTrackingWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: ErrorTrackingWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: ErrorTrackingWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: ErrorTrackingWidgetFieldErrors,
                    { field }: { field: keyof ErrorTrackingWidgetFieldErrors }
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
        widgetConfig: [
            (_, p) => [p.config],
            (config): ErrorTrackingWidgetConfig => parseErrorTrackingWidgetConfig(config),
        ],
        ...widgetEditModalPropSelectors,
        validation: [
            (s) => [s.limit, s.orderBy, s.orderDirection, s.filterTestAccounts, s.widgetConfig],
            (limit, orderBy, orderDirection, filterTestAccounts, widgetConfig) =>
                validateErrorTrackingWidgetConfigInput({
                    limit,
                    orderBy,
                    orderDirection,
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
    }),

    defaults(({ props, values }) => {
        const baseConfig = parseErrorTrackingWidgetConfig(props.config)
        return {
            limit: baseConfig.limit,
            orderBy: baseConfig.orderBy,
            orderDirection: baseConfig.orderDirection,
            ...getWidgetEditModalTileDefaults(props),
            filterTestAccounts: resolveWidgetFilterTestAccounts(
                baseConfig.filterTestAccounts,
                values.filterTestAccountsDefault
            ),
            fieldErrors: {},
            saving: false,
        }
    }),

    listeners(({ actions, props, values }) => ({
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
                    actions.setFieldErrors(error.fieldErrors as ErrorTrackingWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
