import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { isWidgetConfigValidationError } from '../../utils'
import { resolveWidgetFilterTestAccounts, type SessionReplayWidgetConfig } from '../../widget_types/configSchemas'
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
import type { editSessionReplayWidgetModalLogicType } from './editSessionReplayWidgetModalLogicType'
import {
    parseSessionReplayWidgetConfig,
    validateSessionReplayWidgetConfigInput,
    type SessionReplayWidgetFieldErrors,
} from './sessionReplayWidgetConfigValidation'

export type EditSessionReplayWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editSessionReplayWidgetModalLogic = kea<editSessionReplayWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'session_replay', 'editSessionReplayWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        onSaveMetadata: undefined,
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditSessionReplayWidgetModalLogicProps),

    connect({
        values: [filterTestAccountsDefaultsLogic, ['filterTestAccountsDefault']],
    }),

    actions({
        setOrderBy: (orderBy: SessionReplayWidgetConfig['orderBy']) => ({ orderBy }),
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
            'start_time' as SessionReplayWidgetConfig['orderBy'],
            {
                setOrderBy: (
                    _: SessionReplayWidgetConfig['orderBy'],
                    { orderBy }: { orderBy: SessionReplayWidgetConfig['orderBy'] }
                ) => orderBy,
            },
        ],
        ...widgetEditModalListFieldReducers,
        ...widgetEditModalTileReducers,
        ...widgetEditModalFilterTestAccountsReducers,
        ...widgetEditModalFieldErrorsReducers,
        ...widgetEditModalSavingReducers,
    }),

    selectors({
        widgetConfig: [
            (_, p) => [p.config],
            (config): SessionReplayWidgetConfig => parseSessionReplayWidgetConfig(config),
        ],
        ...widgetEditModalPropSelectors,
        validation: [
            (s) => [s.limit, s.orderBy, s.dateFrom, s.filterTestAccounts, s.widgetConfig],
            (limit, orderBy, dateFrom, filterTestAccounts, widgetConfig) =>
                validateSessionReplayWidgetConfigInput({
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
        const baseConfig = parseSessionReplayWidgetConfig(props.config)

        return {
            ...getWidgetEditModalTileDefaults(props),
            limit: baseConfig.limit,
            orderBy: baseConfig.orderBy,
            dateFrom: baseConfig.dateRange?.date_from ?? '-7d',
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
            const result = validateSessionReplayWidgetConfigInput({
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
                    actions.setFieldErrors(error.fieldErrors as SessionReplayWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
