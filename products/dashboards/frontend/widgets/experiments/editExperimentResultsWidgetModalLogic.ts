import { actions, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { isWidgetConfigValidationError } from '../../utils'
import {
    widgetEditModalPropSelectors,
    widgetEditModalTileActions,
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editExperimentResultsWidgetModalLogicType } from './editExperimentResultsWidgetModalLogicType'
import {
    parseExperimentResultsWidgetConfig,
    validateExperimentResultsWidgetConfigInput,
    type ExperimentResultsWidgetFieldErrors,
} from './experimentResultsWidgetConfigValidation'

export type EditExperimentResultsWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editExperimentResultsWidgetModalLogic = kea<editExperimentResultsWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'experiments', 'editExperimentResultsWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditExperimentResultsWidgetModalLogicProps),

    actions({
        setExperimentId: (experimentId: number | null) => ({ experimentId }),
        ...widgetEditModalTileActions,
        setFieldErrors: (fieldErrors: ExperimentResultsWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof ExperimentResultsWidgetFieldErrors) => ({ field }),
        submit: true,
        submitSuccess: true,
        submitFailure: true,
    }),

    reducers({
        experimentId: [
            null as number | null,
            {
                setExperimentId: (_: number | null, { experimentId }: { experimentId: number | null }) => experimentId,
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
            {} as ExperimentResultsWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: ExperimentResultsWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: ExperimentResultsWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: ExperimentResultsWidgetFieldErrors,
                    { field }: { field: keyof ExperimentResultsWidgetFieldErrors }
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
        ...widgetEditModalPropSelectors,
        validation: [
            (s) => [s.experimentId],
            (experimentId) => validateExperimentResultsWidgetConfigInput({ experimentId }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): ExperimentResultsWidgetFieldErrors => {
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
        const baseConfig = parseExperimentResultsWidgetConfig(props.config)

        return {
            experimentId: baseConfig.experimentId ?? null,
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
                    actions.setFieldErrors(error.fieldErrors as ExperimentResultsWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
