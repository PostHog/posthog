import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'

import { EXPERIMENT_TARGET_SELECTOR } from 'lib/actionUtils'
import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { percentageDistribution } from '~/scenes/experiments/utils'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { WebExperiment, WebExperimentDraftType, WebExperimentForm } from '~/toolbar/types'
import { elementToQuery } from '~/toolbar/utils'
import { Experiment, ExperimentIdType } from '~/types'

import type { experimentsTabLogicType } from './experimentsTabLogicType'

function newExperiment(): WebExperimentForm {
    return {
        name: '',
        variants: {
            control: {
                transforms: [],
                rollout_percentage: 50,
            },
            test: {
                is_new: true,
                transforms: [{}],
                rollout_percentage: 50,
            },
        },
        original_html_state: {},
    }
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
        applyVariant: (newVariantKey: string) => ({
            newVariantKey,
        }),
        addNewTransformation: (variant: string) => ({ variant }),
        removeElement: (variant: string, index: number) => ({ variant, index }),
        inspectForElementWithIndex: (variant: string, type: ElementSelectorType, index: number | null) => ({
            variant,
            type,
            index,
        }),
        editSelectorWithIndex: (variant: string, index: number | null) => ({ variant, index }),
        inspectElementSelected: (
            element: HTMLElement,
            variant: string,
            index: number | null,
            selector?: string | null
        ) => ({
            element,
            variant,
            index,
            selector,
        }),
        saveExperiment: (formValues: WebExperimentForm) => ({ formValues }),
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
        actions: [experimentsLogic, ['getExperiments']],
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
            'all-elements',
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
            defaults: {
                name: '',
                variants: {},
                original_html_state: {},
            } as WebExperimentForm,
            errors: ({ name }) => ({
                name: !name ? 'Please enter a name for this experiment' : undefined,
            }),
            submit: async (formValues, breakpoint) => {
                const experimentToSave = {
                    ...formValues,
                }

                // This property is only used in the editor to undo transforms
                delete experimentToSave.original_html_state

                const { apiURL, temporaryToken } = values
                const { selectedExperimentId } = values

                let response: WebExperiment
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
            (s) => [s.experimentForm],
            (experimentForm: WebExperimentForm): boolean | undefined => {
                /*Only show the remove button if all of these conditions are met:
                1. The experiment is still in draft form
                2. there's more than one test variant, and the variant is not control*/
                return (
                    experimentForm.start_date == null &&
                    experimentForm.variants &&
                    Object.keys(experimentForm.variants).length > 2
                )
            },
        ],
        addVariantAvailable: [
            (s) => [s.experimentForm],
            (experimentForm: WebExperimentForm): boolean | undefined => {
                /*Only show the add button if all of these conditions are met:
                1. The experiment is still in draft form*/
                return experimentForm.start_date == null
            },
        ],
        selectedExperiment: [
            (s) => [s.selectedExperimentId, s.allExperiments],
            (selectedExperimentId, allExperiments: WebExperiment[]): Experiment | WebExperimentDraftType | null => {
                if (selectedExperimentId === 'new') {
                    return newExperiment()
                }
                return allExperiments.find((a) => a.id === selectedExperimentId) || null
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        selectedExperiment: (selectedExperiment: Experiment | WebExperimentDraftType | null) => {
            if (!selectedExperiment) {
                actions.setExperimentFormValues({ name: '', variants: {} })
            } else {
                // Build original_html_state from existing selectors
                const original_html_state: Record<string, { html: string; css?: string }> = {}

                if ((selectedExperiment as WebExperiment).variants) {
                    Object.values((selectedExperiment as WebExperiment).variants).forEach((variant) => {
                        variant.transforms?.forEach((transform) => {
                            if (transform.selector) {
                                const element = document.querySelector(transform.selector) as HTMLElement
                                if (element) {
                                    const style = element.getAttribute('style')
                                    original_html_state[transform.selector] = {
                                        html: element.innerHTML,
                                        ...(style && { css: style }),
                                    }
                                }
                            }
                        })
                    })
                }

                actions.setExperimentFormValues({
                    name: selectedExperiment.name,
                    variants: (selectedExperiment as WebExperiment).variants
                        ? (selectedExperiment as WebExperiment).variants
                        : {},
                    original_html_state,
                })

                // TODO: refactor into a single actions to select + apply changes
                actions.applyVariant('control')
                actions.selectVariant('control')
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
            actions.showButtonExperiments()
            toolbarLogic.actions.setVisibleMenu('experiments')
        },
        inspectElementSelected: ({ element, variant, index, selector }) => {
            if (values.experimentForm?.variants) {
                const currentVariant = values.experimentForm.variants[variant]
                if (currentVariant && index !== null && currentVariant.transforms.length > index) {
                    if (!selector) {
                        selector = element.id ? `#${element.id}` : elementToQuery(element, [])
                    }
                    if (!selector) {
                        return
                    }

                    // Restore original html state for previous selector
                    const previousSelector = currentVariant.transforms[index].selector
                    if (previousSelector) {
                        const originalHtmlState = values.experimentForm.original_html_state?.[previousSelector]
                        if (originalHtmlState) {
                            const previousElement = document.querySelector(previousSelector) as HTMLElement
                            previousElement.innerHTML = originalHtmlState.html
                            if (originalHtmlState.css) {
                                previousElement.setAttribute('style', originalHtmlState.css)
                            }
                        }
                    }

                    // Update state
                    const updatedVariants = {
                        ...values.experimentForm.variants,
                        [variant]: {
                            ...currentVariant,
                            transforms: currentVariant.transforms.map((t, i) =>
                                i === index
                                    ? {
                                          selector,
                                          html: element.innerHTML,
                                          ...(element.getAttribute('style') && { css: element.getAttribute('style') }),
                                      }
                                    : t
                            ),
                        },
                    }
                    actions.setExperimentFormValue('variants', updatedVariants)

                    // Save the original state to undo transforms on variant change
                    actions.setExperimentFormValue('original_html_state', {
                        ...values.experimentForm.original_html_state,
                        [selector]: {
                            html: element.innerHTML,
                            ...(element.getAttribute('style') && { css: element.getAttribute('style') }),
                        },
                    })
                }
            }
        },
        removeVariant: ({ variant }) => {
            if (values.experimentForm && values.experimentForm.variants) {
                delete values.experimentForm.variants[variant]
                actions.setExperimentFormValue('variants', values.experimentForm.variants)
                actions.rebalanceRolloutPercentage()
                actions.selectVariant('control')
            }
        },
        applyVariant: ({ newVariantKey }) => {
            if (values.experimentForm && values.experimentForm.variants) {
                const selectedVariant = values.experimentForm.variants[newVariantKey]
                if (selectedVariant) {
                    // Restore original HTML state
                    Object.entries(values.experimentForm.original_html_state || {}).forEach(
                        ([selector, originalState]) => {
                            const elements = document.querySelectorAll(selector)
                            elements.forEach((element) => {
                                const htmlElement = element as HTMLElement
                                if (htmlElement) {
                                    htmlElement.innerHTML = originalState.html
                                    htmlElement.setAttribute('style', originalState.css)
                                }
                            })
                        }
                    )

                    // Apply variant transforms
                    selectedVariant.transforms?.forEach((transform) => {
                        if (transform.selector) {
                            const elements = document.querySelectorAll(transform.selector)
                            elements.forEach((element) => {
                                const htmlElement = element as HTMLElement
                                if (htmlElement) {
                                    if (transform.html) {
                                        htmlElement.innerHTML = transform.html
                                    }

                                    if (transform.css) {
                                        htmlElement.setAttribute('style', transform.css)
                                    }
                                }
                            })
                        }
                    })
                }
            }
        },
        rebalanceRolloutPercentage: () => {
            const perVariantRollout = percentageDistribution(Object.keys(values.experimentForm.variants || {}).length)

            let i = 0
            for (const existingVariant in values.experimentForm.variants) {
                if (values.experimentForm.variants[existingVariant]) {
                    values.experimentForm.variants[existingVariant].rollout_percentage = Number(perVariantRollout[i])
                    i++
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
                    transforms: [{}],
                    conditions: null,
                    rollout_percentage: 0,
                }

                actions.setExperimentFormValue('variants', values.experimentForm.variants)
                actions.rebalanceRolloutPercentage()
                actions.selectVariant(nextVariantName)
            }
        },
        addNewTransformation: ({ variant }) => {
            if (values.experimentForm.variants) {
                const webVariant = values.experimentForm.variants[variant]
                if (webVariant) {
                    if (webVariant.transforms == undefined) {
                        webVariant.transforms = []
                    }

                    webVariant.transforms.push({})

                    actions.setExperimentFormValue('variants', values.experimentForm.variants)
                    actions.selectVariant(variant)
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
        selectVariant: ({ variant }) => {
            // Deactivate element inspection when switching variant
            actions.inspectForElementWithIndex(variant, 'all-elements', null)
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.getExperiments()
        },
    })),
])
