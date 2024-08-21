import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { experimentsLogic } from '~/toolbar/experiments/experimentsLogic'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import {ExperimentDraftType, ExperimentForm, WebExperiment, WebExperimentVariant} from '~/toolbar/types'
import { experimentStepToExperimentStepFormItem, elementToExperimentStep, stepToDatabaseFormat } from '~/toolbar/utils'
import { Experiment, ElementType } from '~/types'

import type { experimentsTabLogicType } from './experimentsTabLogicType'

function newExperiment(element: HTMLElement | null, dataAttributes: string[] = []): ExperimentDraftType {
    return {
        name: '',
        // steps: [
        //     element
        //         ? experimentStepToExperimentStepFormItem(elementToExperimentStep(element, dataAttributes), true)
        //         : {},
        // ],
    }
}

function toElementsChain(element: HTMLElement): ElementType[] {
    const chain: HTMLElement[] = []
    let currentElement: HTMLElement | null | undefined = element
    while (currentElement && currentElement !== document.documentElement) {
        chain.push(currentElement)
        currentElement = currentElement.parentElement
    }
    return chain.map(
        (element, index) =>
            ({
                attr_class: element.getAttribute('class')?.split(' '),
                attr_id: element.getAttribute('id') || undefined,
                attributes: Array.from(element.attributes).reduce((acc, attr) => {
                    if (!acc[attr.name]) {
                        acc[attr.name] = attr.value
                    } else {
                        acc[attr.name] += ` ${attr.value}`
                    }
                    return acc
                }, {} as Record<string, string>),
                href: element.getAttribute('href') || undefined,
                tag_name: element.tagName.toLowerCase(),
                text: index === 0 ? element.innerText : undefined,
            } as ElementType)
    )
}

export const experimentsTabLogic = kea<experimentsTabLogicType>([
    path(['toolbar', 'experiments', 'experimentsTabLogic']),
    actions({
        selectExperiment: (id: number | 'new' | null) => ({ id: id || null }),
        newExperiment: (element?: HTMLElement) => ({
            element: element || null,
        }),
        inspectForElementWithIndex: (index: number | null) => ({ index }),
        editSelectorWithIndex: (index: number | null) => ({ index }),
        inspectElementSelected: (element: HTMLElement, index: number | null) => ({ element, index }),
        incrementCounter: true,
        saveExperiment: (formValues: ExperimentForm) => ({ formValues }),
        deleteExperiment: true,
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
            ],
            experimentsLogic,
            ['allExperiments'],
        ],
    })),

    reducers({
        experimentFormElementsChains: [
            {} as Record<number, ElementType[]>,
            {
                inspectElementSelected: (state, { element, index }) =>
                    index === null
                        ? []
                        : {
                              ...state,
                              [index]: toElementsChain(element),
                          },
                newExperiment: (_, { element }) => ({
                    0: element ? toElementsChain(element) : [],
                }),
            },
        ],
        buttonExperimentsVisible: [
            false,
            {
                showButtonExperiments: () => true,
                hideButtonExperiments: () => false,
            },
        ],
        selectedExperimentId: [
            null as number | 'new' | null,
            {
                selectExperiment: (_, { id }) => id,
                newExperiment: () => 'new',
            },
        ],
        newExperimentForElement: [
            null as HTMLElement | null,
            {
                newExperiment: (_, { element }) => element,
                selectExperiment: () => null,
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
        editingSelector: [
            null as number | null,
            {
                editSelectorWithIndex: (_, { index }) => index,
            },
        ],
        counter: [
            0,
            {
                incrementCounter: (state) => state + 1,
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
            defaults: { name: null, variants: [{}] as unknown as WebExperimentVariant[] }  as unknown as ExperimentForm,
            errors: ({ name }) => ({
                name: !name || !name.length ? 'Must name this experiment' : undefined,
            }),
            submit: async (formValues, breakpoint) => {
                const experimentToSave = {
                    ...formValues,
                    steps: formValues.variants?.map(stepToDatabaseFormat) || [],
                }
                const { apiURL, temporaryToken } = values
                const { selectedExperimentId } = values

                let response: Experiment
                if (selectedExperimentId && selectedExperimentId !== 'new') {
                    response = await api.update(
                        `${apiURL}/api/projects/@current/experiments/${selectedExperimentId}/?temporary_token=${temporaryToken}`,
                        experimentToSave
                    )
                } else {
                    response = await api.create(
                        `${apiURL}/api/projects/@current/experiments/?temporary_token=${temporaryToken}`,
                        experimentToSave
                    )
                }
                breakpoint()

                experimentsLogic.actions.updateExperiment({ experiment: response })
                actions.selectExperiment(null)

                lemonToast.success('Experiment saved', {
                    button: {
                        label: 'Open in PostHog',
                        action: () => window.open(`${apiURL}${urls.experiment(response.id)}`, '_blank'),
                    },
                })
            },

            // whether we show errors after touch (true) or submit (false)
            showErrorsOnTouch: true,
            // show errors even without submitting first
            alwaysShowErrors: false,
        },
    })),

    selectors({
        editingSelectorValue: [
            (s) => [s.editingSelector, s.experimentForm],
            (editingSelector, experimentForm): string | null => {
                if (editingSelector === null) {
                    return null
                }
                const selector = experimentForm.variants?.[editingSelector].transforms[0].selector
                return selector || null
            },
        ],
        elementsChainBeingEdited: [
            (s) => [s.editingSelector, s.experimentFormElementsChains],
            (editingSelector, elementChains): ElementType[] => {
                if (editingSelector === null) {
                    return []
                }
                return elementChains[editingSelector] || []
            },
        ],
        selectedExperiment: [
            (s) => [s.selectedExperimentId, s.newExperimentForElement, s.allExperiments, s.dataAttributes],
            (
                selectedExperimentId,
                newExperimentForElement,
                allExperiments,
                dataAttributes
            ): Experiment | ExperimentDraftType | null => {
                if (selectedExperimentId === 'new') {
                    return newExperiment(newExperimentForElement, dataAttributes)
                }
                return allExperiments.find((a) => a.id === selectedExperimentId) || null
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        selectedExperiment: (selectedExperiment: Experiment | ExperimentDraftType | null) => {
            console.log(`latest: selectedExperiment is `, selectedExperiment)
            if (!selectedExperiment) {
                actions.setExperimentFormValues({ name: null, variants: [{}] })
            } else {

                // const webExperiment = (selectedExperiment as WebExperiment)
                // actions.setExperimentFormValues({
                //     ...selectedExperiment,
                //     elements: selectedExperiment.variants
                //         ? selectedExperiment.elements.map((element) =>
                //               experimentStepToExperimentStepFormItem(step, false)
                //           )
                //         : [{}],
                // })

                actions.setExperimentFormValues({
                    name: selectedExperiment.name,
                    variants: (selectedExperiment as WebExperiment).variants ? (selectedExperiment as WebExperiment).variants : [{}]
                })
            }
        },
    })),

    listeners(({ actions, values }) => ({
        setElementSelector: ({ selector, index }) => {
            if (values.experimentForm) {
                const steps = [...(values.experimentForm.steps || [])]
                if (steps && steps[index]) {
                    steps[index].selector = selector
                }
                actions.setExperimentFormValue('steps', steps)
            }
        },
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
        inspectElementSelected: ({ element, index }) => {
            if (values.experimentForm) {
                const experimentStep = experimentStepToExperimentStepFormItem(
                    elementToExperimentStep(element, values.dataAttributes),
                    true
                )
                const newSteps = (values.experimentForm.steps || []).map((step, i) =>
                    // null index implicitly means "new step front of the list"
                    i === (index ?? 0) ? experimentStep : step
                )

                actions.setExperimentFormValue('steps', newSteps)
                actions.incrementCounter()
            }
        },
        deleteExperiment: async () => {
            const { selectedExperimentId, apiURL, temporaryToken } = values
            if (selectedExperimentId && selectedExperimentId !== 'new') {
                await api.delete(
                    `${apiURL}/api/projects/@current/experiments/${selectedExperimentId}/?temporary_token=${temporaryToken}`
                )
                experimentsLogic.actions.deleteExperiment({ id: selectedExperimentId })
                actions.selectExperiment(null)
                lemonToast.info('Experiment deleted')
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
            const { userIntent, selectedExperimentId } = values
            if (userIntent === 'edit-experiment') {
                actions.selectExperiment(selectedExperimentId)
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
