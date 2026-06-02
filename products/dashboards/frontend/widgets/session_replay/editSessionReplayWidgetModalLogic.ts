import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { isWidgetConfigValidationError } from '../../utils'
import {
    resolveWidgetFilterTestAccounts,
    type SessionReplayWidgetConfig,
    type WidgetDateFromValue,
} from '../../widget_types/configSchemas'
import {
    widgetEditModalFilterTestAccountsActions,
    widgetEditModalListFieldActions,
    widgetEditModalPropSelectors,
    widgetEditModalTileActions,
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
        setOrderBy: (orderBy: string) => ({ orderBy }),
        ...widgetEditModalListFieldActions,
        ...widgetEditModalTileActions,
        ...widgetEditModalFilterTestAccountsActions,
        setFieldErrors: (fieldErrors: SessionReplayWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof SessionReplayWidgetFieldErrors) => ({ field }),
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
                    { orderBy }: { orderBy: string }
                ): SessionReplayWidgetConfig['orderBy'] => orderBy as SessionReplayWidgetConfig['orderBy'],
            },
        ],
        limit: [
            10,
            {
                setLimit: (_: number, { limit }: { limit: number }) => limit,
            },
        ],
        dateFrom: [
            '-7d',
            {
                setDateFrom: (_: WidgetDateFromValue, { dateFrom }: { dateFrom: string }): WidgetDateFromValue =>
                    dateFrom as WidgetDateFromValue,
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
            {} as SessionReplayWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: SessionReplayWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: SessionReplayWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: SessionReplayWidgetFieldErrors,
                    { field }: { field: keyof SessionReplayWidgetFieldErrors }
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
                submit: (_state: boolean, _payload: { value: true }) => true,
                submitSuccess: (_state: boolean, _payload: { value: true }) => false,
                submitFailure: (_state: boolean, _payload: { value: true }) => false,
            },
        ],
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
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): SessionReplayWidgetFieldErrors => {
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
        const baseConfig = parseSessionReplayWidgetConfig(props.config)

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
