import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import type { SessionReplayWidgetConfig } from '../../generated/widget-configs.zod'
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
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditSessionReplayWidgetModalLogicProps),

    connect(() => ({
        values: [filterTestAccountsDefaultsLogic, ['filterTestAccountsDefault']],
    })),

    actions({
        setOrderBy: (orderBy: string) => ({ orderBy }),
        setOrderDirection: (orderDirection: SessionReplayWidgetConfig['orderDirection']) => ({ orderDirection }),
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
        orderDirection: [
            'DESC' as SessionReplayWidgetConfig['orderDirection'],
            {
                setOrderDirection: (
                    _: SessionReplayWidgetConfig['orderDirection'],
                    { orderDirection }: { orderDirection: SessionReplayWidgetConfig['orderDirection'] }
                ): SessionReplayWidgetConfig['orderDirection'] => orderDirection,
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
            (s) => [s.limit, s.orderBy, s.orderDirection, s.filterTestAccounts, s.widgetConfig],
            (limit, orderBy, orderDirection, filterTestAccounts, widgetConfig) =>
                validateSessionReplayWidgetConfigInput({
                    limit,
                    orderBy,
                    orderDirection,
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
                    actions.setFieldErrors(error.fieldErrors as SessionReplayWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
