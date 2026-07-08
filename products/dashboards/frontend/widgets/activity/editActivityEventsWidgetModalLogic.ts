import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import type { ActivityEventsWidgetConfig } from '../../generated/widget-configs.zod'
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
import {
    parseActivityEventsWidgetConfig,
    validateActivityEventsWidgetConfigInput,
    type ActivityEventsWidgetFieldErrors,
} from './activityEventsWidgetConfigValidation'
import type { editActivityEventsWidgetModalLogicType } from './editActivityEventsWidgetModalLogicType'

export type EditActivityEventsWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editActivityEventsWidgetModalLogic = kea<editActivityEventsWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'activity', 'editActivityEventsWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditActivityEventsWidgetModalLogicProps),

    connect(() => ({
        values: [filterTestAccountsDefaultsLogic, ['filterTestAccountsDefault']],
    })),

    actions({
        ...widgetEditModalListFieldActions,
        ...widgetEditModalTileActions,
        ...widgetEditModalFilterTestAccountsActions,
        setFieldErrors: (fieldErrors: ActivityEventsWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof ActivityEventsWidgetFieldErrors) => ({ field }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        limit: [
            25,
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
            {} as ActivityEventsWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: ActivityEventsWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: ActivityEventsWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: ActivityEventsWidgetFieldErrors,
                    { field }: { field: keyof ActivityEventsWidgetFieldErrors }
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
            (config): ActivityEventsWidgetConfig => parseActivityEventsWidgetConfig(config),
        ],
        ...widgetEditModalPropSelectors,
        validation: [
            (s) => [s.limit, s.filterTestAccounts, s.widgetConfig],
            (limit, filterTestAccounts, widgetConfig) =>
                validateActivityEventsWidgetConfigInput({
                    limit,
                    filterTestAccounts,
                    baseConfig: widgetConfig,
                }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): ActivityEventsWidgetFieldErrors => {
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
        const baseConfig = parseActivityEventsWidgetConfig(props.config)

        return {
            limit: baseConfig.limit,
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
                    actions.setFieldErrors(error.fieldErrors as ActivityEventsWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
