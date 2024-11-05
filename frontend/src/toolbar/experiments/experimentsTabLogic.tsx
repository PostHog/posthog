import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import { EXPERIMENT_TARGET_SELECTOR } from 'lib/actionUtils'
import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import {
    ExperimentDraftType,
    ExperimentForm,
    WebExperiment,
    WebExperimentTransform,
    WebExperimentVariant,
} from '~/toolbar/types'
import { elementToQuery } from '~/toolbar/utils'
import { Experiment, ExperimentIdType } from '~/types'

import type { experimentsTabLogicType } from './experimentsTabLogicType'

function newExperiment(): ExperimentForm {
    return {
        name: '',
        variants: {
            control: {
                transforms: [
                    {
                        text: '',
                        html: '',
                    } as unknown as WebExperimentTransform,
                ],
                rollout_percentage: 50,
            },
            test: {
                is_new: true,
                transforms: [
                    {
                        text: '',
                        html: '',
                    } as unknown as WebExperimentTransform,
                ],
                rollout_percentage: 50,
            },
        },
    } as unknown as ExperimentForm
}

const EXPERIMENT_HEADER_TARGETS = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']

const EXPERIMENT_BUTTON_TARGETS = ['input[type="button"]', 'button']

export type ElementSelectorType = 'all-elements' | 'headers' | 'buttons' | 'images'

const ElementSelectorMap: Record<ElementSelectorType, string> = {
    'all-elements': EXPERIMENT_TARGET_SELECTOR,
    headers: EXPERIMENT_HEADER_TARGETS.join(','),
    buttons: EXPERIMENT_BUTTON_TARGETS.join(','),
    images: 'img',
}
export const ElementSelectorButtonTypes = {
    'all-elements': 'All Elements',
    headers: 'Headers',
    buttons: 'Buttons',
    images: 'Images',
}

export const experimentsTabLogic = kea<experimentsTabLogicType>([
    path(['toolbar', 'experiments', 'experimentsTabLogic']),
    actions({
        selectExperiment: (id: ExperimentIdType | null) => ({ id: id || null }),
        selectVariant: (variant: string) => ({ variant }),
        selectElementType: (elementType: ElementSelectorType) => ({ elementType }),
        newExperiment: (element?: HTMLElement) => ({
            element: element || null,
        }),
        addNewVariant: () => ({}),
        rebalanceRolloutPercentage: () => ({}),
        removeVariant: (variant: string) => ({
            variant,
        }),
        applyVariant: (current_variant: string, variant: string) => ({
            current_variant,
            variant,
        }),
        addNewElement: (variant: string) => ({ variant }),
        removeElement: (variant: string, index: number) => ({ variant, index }),
        inspectForElementWithIndex: (variant: string, type: ElementSelectorType, index: number | null) => ({
            variant,
            type,
            index,
        }),
        editSelectorWithIndex: (variant: string, index: number | null) => ({ variant, index }),
        inspectElementSelected: (element: HTMLElement, variant: string, index: number | null) => ({
            element,
            variant,
            index,
        }),
        saveExperiment: (formValues: ExperimentForm) => ({ formValues }),
        showButtonExperiments: true,
        hideButtonExperiments: true,
        setShowExperimentsTooltip: (showExperimentsTooltip: boolean) => ({ showExperimentsTooltip }),
        setElementSelector: (selector: string, index: number) => ({ selector, index }),
    }),

    connect(() => ({
        values: [
            toolbarConfigLogic,
            [
                'dataAttributes',
                'apiURL',
                'temporaryToken',
                'buttonVisible',
                'userIntent',
                'dataAttributes',
                'experimentId',
            ],
            experimentsLogic,
            ['allExperiments'],
        ],
    })),

    reducers({
        buttonExperimentsVisible: [
            false,
            {
                showButtonExperiments: () => true,
                hideButtonExperiments: () => false,
            },
        ],
        selectedExperimentId: [
            null as number | 'new' | 'web' | null,
            {
                selectExperiment: (_, { id }) => id,
                newExperiment: () => 'new',
            },
        ],
        selectedVariant: [
            '',
            {
                selectVariant: (_, { variant }) => variant,
            },
        ],
        selectedElementType: [
            '',
            {
                selectElementType: (_, { elementType }) => elementType,
            },
        ],
        newExperimentForElement: [
            null as HTMLElement | null,
            {
                newExperiment: (_, { element }) => element,
                selectExperiment: () => null,
            },
        ],
        elementSelector: [
            '',
            {
                inspectForElementWithIndex: (_, { type }) => ElementSelectorMap[type] || '',
            },
        ],
        inspectingElement: [
            null as number | null,
            {
                inspectForElementWithIndex: (_, { index }) => index,
                inspectElementSelected: () => null,
                selectExperiment: () => null,
                newExperiment: () => null,
            },
        ],
        showExperimentsTooltip: [
            false,
            {
                setShowExperimentsTooltip: (_, { showExperimentsTooltip }) => showExperimentsTooltip,
            },
        ],
    }),

    forms(({ values, actions }) => ({
        experimentForm: {
            defaults: { name: null, variants: [{}] as unknown as WebExperimentVariant[] } as unknown as ExperimentForm,
            errors: ({ name }) => ({
                name: !name ? 'Please enter a name for this experiment' : undefined,
            }),
            submit: async (formValues, breakpoint) => {
                const experimentToSave = {
                    ...formValues,
                }

                // this property is used in the editor to undo transforms
                // don't need to roundtrip this to the server.
                delete experimentToSave.undo_transforms
                const { apiURL, temporaryToken } = values
                const { selectedExperimentId } = values

                let response: Experiment
                try {
                    if (selectedExperimentId && selectedExperimentId !== 'new') {
                        response = await api.update(
                            `${apiURL}/api/projects/@current/web_experiments/${selectedExperimentId}/?temporary_token=${temporaryToken}`,
                            experimentToSave
                        )
                    } else {
                        response = await api.create(
                            `${apiURL}/api/projects/@current/web_experiments/?temporary_token=${temporaryToken}`,
                            experimentToSave
                        )
                    }

                    experimentsLogic.actions.updateExperiment({ experiment: response })
                    actions.selectExperiment(null)

                    lemonToast.success('Experiment saved', {
                        button: {
                            label: 'Open in PostHog',
                            action: () => window.open(`${apiURL}${urls.experiment(response.id)}`, '_blank'),
                        },
                    })
                    breakpoint()
                } catch (e) {
                    const apiError = e as ApiError
                    if (apiError) {
                        lemonToast.error(`Experiment save failed: ${apiError.data.detail}`)
                    }
                }
            },

            // whether we show errors after touch (true) or submit (false)
            showErrorsOnTouch: true,
            // show errors even without submitting first
            alwaysShowErrors: false,
        },
    })),

    selectors({
        removeVariantAvailable: [
            (s) => [s.experimentForm, s.selectedExperimentId],
            (experimentForm: ExperimentForm, selectedExperimentId: number | 'new' | null): boolean | undefined => {
                /*Only show the remove button if all of these conditions are met:
                1. Its a new Experiment
                2. The experiment is still in draft form
                3. there's more than one test variant, and the variant is not control*/
                return (
                    selectedExperimentId === 'new' &&
                    experimentForm.start_date == null &&
                    experimentForm.variants &&
                    Object.keys(experimentForm.variants).length > 2
                )
            },
        ],
        addVariantAvailable: [
            (s) => [s.experimentForm, s.selectedExperimentId],
            (experimentForm: ExperimentForm, selectedExperimentId: number | 'new' | null): boolean | undefined => {
                /*Only show the add button if all of these conditions are met:
                1. Its a new Experiment
                2. The experiment is still in draft form*/
                return selectedExperimentId === 'new' || experimentForm.start_date == null
            },
        ],
        selectedExperiment: [
            (s) => [s.selectedExperimentId, s.allExperiments],
            (selectedExperimentId, allExperiments: WebExperiment[]): Experiment | ExperimentDraftType | null => {
                if (selectedExperimentId === 'new') {
                    return newExperiment()
                }
                return allExperiments.find((a) => a.id === selectedExperimentId) || null
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        selectedExperiment: (selectedExperiment: Experiment | ExperimentDraftType | null) => {
            if (!selectedExperiment) {
                actions.setExperimentFormValues({ name: '', variants: {} })
            } else {
                actions.setExperimentFormValues({
                    name: selectedExperiment.name,
                    variants: (selectedExperiment as WebExperiment).variants
                        ? (selectedExperiment as WebExperiment).variants
                        : {},
                })
            }
        },
    })),

    listeners(({ actions, values }) => ({
        selectExperiment: ({ id }) => {
            if (id) {
                if (!values.buttonVisible) {
                    toolbarConfigLogic.actions.showButton()
                }

                if (!values.buttonExperimentsVisible) {
                    actions.showButtonExperiments()
                }

                toolbarLogic.actions.setVisibleMenu('experiments')
            }
        },
        newExperiment: () => {
            // if (!values.buttonExperimentsVisible) {
            actions.showButtonExperiments()
            // }
            toolbarLogic.actions.setVisibleMenu('experiments')
        },
        inspectElementSelected: ({ element, variant, index }) => {
            if (values.experimentForm && values.experimentForm.variants) {
                const eVariant = values.experimentForm.variants[variant]
                if (eVariant) {
                    if (index !== null && eVariant.transforms.length > index) {
                        const transform = eVariant.transforms[index]
                        transform.selector = element.id ? `#${element.id}` : elementToQuery(element, [])
                        if (element.textContent) {
                            transform.text = element.textContent
                        }
                        transform.html = element.innerHTML
                        actions.setExperimentFormValue('variants', values.experimentForm.variants)
                    }
                }
            }
        },
        removeVariant: ({ variant }) => {
            if (values.experimentForm && values.experimentForm.variants) {
                delete values.experimentForm.variants[variant]
                actions.setExperimentFormValue('variants', values.experimentForm.variants)
                actions.rebalanceRolloutPercentage()
            }
        },
        applyVariant: ({ current_variant, variant }) => {
            if (values.experimentForm && values.experimentForm.variants) {
                const selectedVariant = values.experimentForm.variants[variant]
                if (selectedVariant) {
                    if (values.experimentForm.undo_transforms === undefined) {
                        values.experimentForm.undo_transforms = []
                    }

                    // run the undo transforms first.
                    values.experimentForm.undo_transforms?.forEach((transform) => {
                        if (transform.selector) {
                            const elements = document.querySelectorAll(transform.selector)
                            elements.forEach((elements) => {
                                const htmlElement = elements as HTMLElement
                                if (htmlElement) {
                                    if (transform.html) {
                                        htmlElement.innerHTML = transform.html
                                    }

                                    if (transform.css) {
                                        htmlElement.setAttribute('style', transform.css)
                                    }

                                    if (transform.text) {
                                        htmlElement.innerText = transform.text
                                    }
                                }
                            })
                        }
                    })

                    selectedVariant.transforms?.forEach((transform) => {
                        if (transform.selector) {
                            const undoTransform: WebExperimentTransform = {
                                selector: transform.selector,
                            }
                            const elements = document.querySelectorAll(transform.selector)
                            elements.forEach((elements) => {
                                const htmlElement = elements as HTMLElement
                                if (htmlElement) {
                                    if (transform.html) {
                                        undoTransform.html = htmlElement.innerHTML
                                        htmlElement.innerHTML = transform.html
                                    }

                                    if (transform.css) {
                                        undoTransform.css = htmlElement.getAttribute('style') || ' '
                                        htmlElement.setAttribute('style', transform.css)
                                    }

                                    if (transform.text) {
                                        undoTransform.text = htmlElement.innerText
                                        htmlElement.innerText = transform.text
                                    }
                                }
                            })

                            if ((current_variant === 'control' || current_variant === '') && variant !== 'control') {
                                values.experimentForm.undo_transforms?.push(undoTransform)
                            }
                        }
                    })
                }
            }
        },
        rebalanceRolloutPercentage: () => {
            const perVariantRollout = Math.round(100 / Object.keys(values.experimentForm.variants || {}).length)
            for (const existingVariant in values.experimentForm.variants) {
                if (values.experimentForm.variants[existingVariant]) {
                    values.experimentForm.variants[existingVariant].rollout_percentage = Number(perVariantRollout)
                }
            }
            actions.setExperimentFormValue('variants', values.experimentForm.variants)
        },
        addNewVariant: () => {
            if (values.experimentForm) {
                const nextVariantName = `variant #${Object.keys(values.experimentForm.variants || {}).length}`

                if (values.experimentForm.variants == undefined) {
                    values.experimentForm.variants = {}
                }

                values.experimentForm.variants[nextVariantName] = {
                    is_new: true,
                    transforms: [
                        {
                            text: '',
                            html: '',
                        } as unknown as WebExperimentTransform,
                    ],
                    conditions: null,
                    rollout_percentage: 0,
                }

                actions.setExperimentFormValue('variants', values.experimentForm.variants)
                actions.rebalanceRolloutPercentage()
            }
        },
        addNewElement: ({ variant }) => {
            if (values.experimentForm.variants) {
                const webVariant = values.experimentForm.variants[variant]
                if (webVariant) {
                    if (webVariant.transforms == undefined) {
                        webVariant.transforms = []
                    }

                    webVariant.transforms.push({
                        text: '',
                        html: '',
                    } as unknown as WebExperimentTransform)

                    actions.setExperimentFormValue('variants', values.experimentForm.variants)
                    actions.selectVariant(variant)
                    actions.inspectForElementWithIndex(variant, 'all-elements', webVariant.transforms.length - 1)
                }
            }
        },
        removeElement: ({ index, variant }) => {
            if (values.experimentForm.variants) {
                const webVariant = values.experimentForm.variants[variant]
                if (webVariant) {
                    webVariant.transforms.splice(index, 1)
                    actions.setExperimentFormValue('variants', values.experimentForm.variants)
                }
            }
        },
        showButtonExperiments: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'experiments', enabled: true })
        },
        hideButtonExperiments: () => {
            actions.setShowExperimentsTooltip(false)
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'experiments', enabled: false })
        },
        [experimentsLogic.actionTypes.getExperimentsSuccess]: () => {
            const { userIntent, experimentId } = values
            if (userIntent === 'edit-experiment') {
                actions.selectExperiment(experimentId)
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'add-experiment') {
                actions.newExperiment()
                toolbarConfigLogic.actions.clearUserIntent()
            } else {
                actions.setShowExperimentsTooltip(true)
            }
        },
        setShowExperimentsTooltip: async ({ showExperimentsTooltip }, breakpoint) => {
            if (showExperimentsTooltip) {
                await breakpoint(1000)
                actions.setShowExperimentsTooltip(false)
            }
        },
    })),
])
