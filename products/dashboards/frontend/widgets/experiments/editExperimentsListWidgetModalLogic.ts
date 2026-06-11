import { actions, defaults, kea, listeners, path, props, reducers, selectors } from 'kea'

import { isWidgetConfigValidationError } from '../../utils'
import {
    widgetEditModalPropSelectors,
    widgetEditModalTileActions,
    buildWidgetTileMetadataPatch,
    getWidgetEditModalTileDefaults,
} from '../editWidgetModalBuilders'
import type { DashboardWidgetEditModalProps } from '../registry'
import type { editExperimentsListWidgetModalLogicType } from './editExperimentsListWidgetModalLogicType'
import {
    parseExperimentsListWidgetConfig,
    validateExperimentsListWidgetConfigInput,
    type ExperimentsListWidgetFieldErrors,
    type ExperimentsListWidgetStatus,
} from './experimentsListWidgetConfigValidation'

export type EditExperimentsListWidgetModalLogicProps = Omit<DashboardWidgetEditModalProps, 'isOpen'>

export const editExperimentsListWidgetModalLogic = kea<editExperimentsListWidgetModalLogicType>([
    path(['products', 'dashboards', 'widgets', 'experiments', 'editExperimentsListWidgetModalLogic']),

    props({
        config: {},
        onSave: async () => {},
        onClose: () => {},
        name: '',
        defaultTitle: 'Untitled',
        description: '',
    } as EditExperimentsListWidgetModalLogicProps),

    actions({
        setLimit: (limit: number) => ({ limit }),
        setStatus: (status: ExperimentsListWidgetStatus) => ({ status }),
        setCreatedBy: (createdBy: number | null) => ({ createdBy }),
        ...widgetEditModalTileActions,
        setFieldErrors: (fieldErrors: ExperimentsListWidgetFieldErrors) => ({ fieldErrors }),
        clearFieldError: (field: keyof ExperimentsListWidgetFieldErrors) => ({ field }),
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
        status: [
            'all' as ExperimentsListWidgetStatus,
            {
                setStatus: (
                    _: ExperimentsListWidgetStatus,
                    { status }: { status: ExperimentsListWidgetStatus }
                ): ExperimentsListWidgetStatus => status,
            },
        ],
        createdBy: [
            null as number | null,
            {
                setCreatedBy: (_: number | null, { createdBy }: { createdBy: number | null }) => createdBy,
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
            {} as ExperimentsListWidgetFieldErrors,
            {
                setFieldErrors: (
                    _: ExperimentsListWidgetFieldErrors,
                    { fieldErrors }: { fieldErrors: ExperimentsListWidgetFieldErrors }
                ) => fieldErrors,
                clearFieldError: (
                    state: ExperimentsListWidgetFieldErrors,
                    { field }: { field: keyof ExperimentsListWidgetFieldErrors }
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
            (s) => [s.limit, s.status, s.createdBy],
            (limit, status, createdBy) =>
                validateExperimentsListWidgetConfigInput({
                    limit,
                    status,
                    createdBy,
                }),
        ],
        activeFieldErrors: [
            (s) => [s.validation, s.fieldErrors],
            (validation, fieldErrors): ExperimentsListWidgetFieldErrors => {
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
        const baseConfig = parseExperimentsListWidgetConfig(props.config)

        return {
            limit: baseConfig.limit,
            status: baseConfig.status,
            createdBy: baseConfig.createdBy ?? null,
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
                    actions.setFieldErrors(error.fieldErrors as ExperimentsListWidgetFieldErrors)
                    return
                }
                throw error
            }
        },
    })),
])
