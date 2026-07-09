import { actions, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import type { SurveyResultsWidgetConfig } from '../../generated/widget-configs.zod'
import { isWidgetConfigValidationError } from '../../utils'
import {
    widgetEditModalPropSelectors,
    widgetEditModalTileActions,
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editSurveyResultsWidgetModalLogicType } from './editSurveyResultsWidgetModalLogicType'
import {
    dateFromValueForConfig,
    parseSurveyResultsWidgetConfig,
    validateSurveyResultsWidgetConfigInput,
    SURVEY_DATE_ALL_TIME,
    type SurveyResultsWidgetFieldErrors,
    type SurveyWidgetDateFrom,
} from './surveysWidgetConfigValidation'

export type EditSurveyResultsWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editSurveyResultsWidgetModalLogic = kea<editSurveyResultsWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'surveys', 'editSurveyResultsWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditSurveyResultsWidgetModalLogicProps),

    actions({
        ...widgetEditModalTileActions,
        setLimit: (limit: number) => ({ limit }),
        setDateFrom: (dateFrom: SurveyWidgetDateFrom) => ({ dateFrom }),
        setFieldErrors: (fieldErrors: SurveyResultsWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof SurveyResultsWidgetFieldErrors) => ({ field }),
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
        dateFrom: [
            SURVEY_DATE_ALL_TIME as SurveyWidgetDateFrom,
            {
                setDateFrom: (_: SurveyWidgetDateFrom, { dateFrom }: { dateFrom: SurveyWidgetDateFrom }) => dateFrom,
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
            {} as SurveyResultsWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: SurveyResultsWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: SurveyResultsWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: SurveyResultsWidgetFieldErrors,
                    { field }: { field: keyof SurveyResultsWidgetFieldErrors }
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
            (config): SurveyResultsWidgetConfig => parseSurveyResultsWidgetConfig(config),
        ],
        ...widgetEditModalPropSelectors,
        validation: [
            (s) => [s.limit, s.dateFrom, s.widgetConfig],
            // The survey is chosen on the tile filter bar; read it from the persisted config so saving
            // the date range / limit preserves the selection.
            (limit, dateFrom, widgetConfig) =>
                validateSurveyResultsWidgetConfigInput({
                    surveyId: widgetConfig.surveyId ?? null,
                    limit,
                    dateFrom,
                    baseConfig: widgetConfig,
                }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): SurveyResultsWidgetFieldErrors => {
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
        const baseConfig = parseSurveyResultsWidgetConfig(props.config)

        return {
            limit: baseConfig.limit ?? 10,
            dateFrom: dateFromValueForConfig(baseConfig),
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
                    actions.setFieldErrors(error.fieldErrors as SurveyResultsWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
