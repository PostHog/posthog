import { actions, connect, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { isWidgetConfigValidationError } from '../../utils'
import { resolveWidgetFilterTestAccounts, type SessionReplayWidgetConfig } from '../../widget_types/configSchemas'
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

    connect({
        values: [filterTestAccountsDefaultsLogic, ['filterTestAccountsDefault']],
    }),

    actions({
        setLimit: (limit: number) => ({ limit }),
        setOrderBy: (orderBy: string) => ({ orderBy }),
        setDateFrom: (dateFrom: string) => ({ dateFrom }),
        setTileName: (tileName: string) => ({ tileName }),
        setTileDescription: (tileDescription: string) => ({ tileDescription }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        setFieldErrors: (fieldErrors: SessionReplayWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof SessionReplayWidgetFieldErrors) => ({ field }),
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
            'start_time',
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
            {} as SessionReplayWidgetFieldErrors,
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
        widgetConfig: [
            (_, p) => [p.config],
            (config): SessionReplayWidgetConfig => parseSessionReplayWidgetConfig(config),
        ],
        onClose: [(_, p) => [p.onClose], (onClose) => onClose],
        defaultTitle: [(_, p) => [p.defaultTitle], (defaultTitle) => defaultTitle ?? 'Untitled'],
        onSaveMetadata: [(_, p) => [p.onSaveMetadata], (onSaveMetadata) => onSaveMetadata],
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
            tileName: props.name ?? '',
            tileDescription: props.description ?? '',
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
                    actions.setFieldErrors(error.fieldErrors as SessionReplayWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
