import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { exceptionIngestionLogic } from 'products/error_tracking/frontend/components/SetupPrompt/exceptionIngestionLogic'

import { isWidgetConfigValidationError } from '../../utils'
import { resolveWidgetFilterTestAccounts, type ErrorTrackingWidgetConfig } from '../../widget_types/configSchemas'
import {
    widgetEditModalFieldErrorsActions,
    widgetEditModalFieldErrorsReducers,
    widgetEditModalFilterTestAccountsActions,
    widgetEditModalFilterTestAccountsReducers,
    widgetEditModalListFieldActions,
    widgetEditModalListFieldReducers,
    widgetEditModalPropSelectors,
    widgetEditModalSavingReducers,
    widgetEditModalTileActions,
    widgetEditModalTileReducers,
    widgetEditModalValidationSelectors,
} from '../editWidgetModalBuilders'
import { getWidgetEditModalTileDefaults, saveWidgetTileMetadataAfterConfig } from '../editWidgetModalTileUtils'
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
        setOrderBy: (orderBy: string) => ({ orderBy }),
        ...widgetEditModalListFieldActions,
        ...widgetEditModalTileActions,
        ...widgetEditModalFilterTestAccountsActions,
        ...widgetEditModalFieldErrorsActions,
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        orderBy: [
            'occurrences',
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        ...widgetEditModalListFieldReducers,
        ...widgetEditModalTileReducers,
        ...widgetEditModalFilterTestAccountsReducers,
        ...widgetEditModalFieldErrorsReducers,
        ...widgetEditModalSavingReducers,
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
        ...widgetEditModalValidationSelectors,
    }),

    defaults(({ props, values }) => {
        const baseConfig = parseErrorTrackingWidgetConfig(props.config)

        return {
            limit: baseConfig.limit,
            orderBy: baseConfig.orderBy,
            dateFrom: baseConfig.dateRange?.date_from ?? '-7d',
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
            const result = validateErrorTrackingWidgetConfigInput({
                limit: values.limit,
                orderBy: values.orderBy,
                dateFrom: values.dateFrom,
                filterTestAccounts: values.filterTestAccounts,
                baseConfig: values.widgetConfig,
            })

            if (!result.success) {
                actions.setFieldErrors(result.fieldErrors)
                return
            }

            try {
                await props.onSave(result.config)
                await saveWidgetTileMetadataAfterConfig(props, values.tileName, values.tileDescription)
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
