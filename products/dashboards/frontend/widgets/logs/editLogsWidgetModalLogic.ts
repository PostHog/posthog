import { actions, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import type { LogsWidgetConfig } from '../../generated/widget-configs.zod'
import { isWidgetConfigValidationError } from '../../utils'
import type { WidgetDateFromValue } from '../../widget_types/widgetConfigShared'
import {
    widgetEditModalListFieldActions,
    widgetEditModalPropSelectors,
    widgetEditModalTileActions,
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editLogsWidgetModalLogicType } from './editLogsWidgetModalLogicType'
import {
    LOGS_DEFAULT_DATE_FROM,
    parseLogsWidgetConfig,
    validateLogsWidgetConfigInput,
    type LogsTimezone,
    type LogsWidgetFieldErrors,
} from './logsWidgetConfigValidation'

export type EditLogsWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editLogsWidgetModalLogic = kea<editLogsWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'logs', 'editLogsWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditLogsWidgetModalLogicProps),

    actions({
        ...widgetEditModalListFieldActions,
        ...widgetEditModalTileActions,
        setWrapLines: (wrapLines: boolean) => ({ wrapLines }),
        setTimezone: (timezone: LogsTimezone) => ({ timezone }),
        setFieldErrors: (fieldErrors: LogsWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof LogsWidgetFieldErrors) => ({ field }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        limit: [
            50,
            {
                setLimit: (_: number, { limit }: { limit: number }) => limit,
            },
        ],
        wrapLines: [
            false,
            {
                setWrapLines: (_: boolean, { wrapLines }: { wrapLines: boolean }) => wrapLines,
            },
        ],
        timezone: [
            'UTC' as LogsTimezone,
            {
                setTimezone: (_: LogsTimezone, { timezone }: { timezone: LogsTimezone }) => timezone,
            },
        ],
        dateFrom: [
            LOGS_DEFAULT_DATE_FROM as WidgetDateFromValue,
            {
                setDateFrom: (_: WidgetDateFromValue, { dateFrom }: { dateFrom: WidgetDateFromValue }) => dateFrom,
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
        fieldErrors: [
            {} as LogsWidgetFieldErrors,
            {
                setFieldErrors: (_: LogsWidgetFieldErrors, { fieldErrors }: { fieldErrors: LogsWidgetFieldErrors }) =>
                    fieldErrors,
                clearFieldError: (state: LogsWidgetFieldErrors, { field }: { field: keyof LogsWidgetFieldErrors }) => {
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
        widgetConfig: [(_, p) => [p.config], (config): LogsWidgetConfig => parseLogsWidgetConfig(config)],
        ...widgetEditModalPropSelectors,
        validation: [
            (s) => [s.limit, s.wrapLines, s.timezone, s.dateFrom, s.widgetConfig],
            (limit, wrapLines, timezone, dateFrom, widgetConfig) =>
                validateLogsWidgetConfigInput({
                    limit,
                    wrapLines,
                    timezone,
                    dateFrom,
                    baseConfig: widgetConfig,
                }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): LogsWidgetFieldErrors => {
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

    defaults(({ props }) => {
        const baseConfig = parseLogsWidgetConfig(props.config)

        return {
            limit: baseConfig.limit,
            wrapLines: baseConfig.wrapLines ?? false,
            timezone: (baseConfig.timezone ?? 'UTC') as LogsTimezone,
            dateFrom: baseConfig.dateRange?.date_from ?? LOGS_DEFAULT_DATE_FROM,
            ...getWidgetEditModalTileDefaults(props),
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
                    actions.setFieldErrors(error.fieldErrors as LogsWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
