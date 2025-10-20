import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ActionDraftType, ActionForm } from '~/toolbar/types'
import { actionStepToActionStepFormItem, elementToActionStep, stepToDatabaseFormat } from '~/toolbar/utils'
import { AccessControlLevel, ActionType, ElementType } from '~/types'

import { ActionStepPropertyKey } from './ActionStep'
import type { actionsTabLogicType } from './actionsTabLogicType'

function newAction(
    element: HTMLElement | null,
    dataAttributes: string[] = [],
    name: string | null,
    includedPropertyKeys?: ActionStepPropertyKey[]
): ActionDraftType {
    return {
        name: name || '',
        steps: [
            element
                ? actionStepToActionStepFormItem(
                      elementToActionStep(element, dataAttributes),
                      true,
                      includedPropertyKeys
                  )
                : {},
        ],
        pinned_at: null,
        user_access_level: AccessControlLevel.Editor,
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

                attributes: Array.from(element.attributes).reduce(
                    (acc, attr) => {
                        if (!acc[attr.name]) {
                            acc[attr.name] = attr.value
                        } else {
                            acc[attr.name] += ` ${attr.value}`
                        }
                        return acc
                    },
                    {} as Record<string, string>
                ),

                href: element.getAttribute('href') || undefined,
                tag_name: element.tagName.toLowerCase(),
                text: index === 0 ? element.innerText : undefined,
            }) as ElementType
    )
}

export const actionsTabLogic = kea<actionsTabLogicType>([
    path(['toolbar', 'actions', 'actionsTabLogic']),
    actions({
        selectAction: (id: number | null) => ({ id: id || null }),
        newAction: (element?: HTMLElement) => ({
            element: element || null,
        }),
        inspectForElementWithIndex: (index: number | null) => ({ index }),
        editSelectorWithIndex: (index: number | null) => ({ index }),
        inspectElementSelected: (element: HTMLElement, index: number | null) => ({ element, index }),
        incrementCounter: true,
        saveAction: (formValues: ActionForm) => ({ formValues }),
        showButtonActions: true,
        hideButtonActions: true,
        setShowActionsTooltip: (showActionsTooltip: boolean) => ({ showActionsTooltip }),
        setElementSelector: (selector: string, index: number) => ({ selector, index }),
        setAutomaticActionCreationEnabled: (enabled: boolean, name?: string) => ({ enabled, name }),
        actionCreatedSuccess: (action: ActionType) => ({ action }),
        setautomaticCreationIncludedPropertyKeys: (keys: ActionStepPropertyKey[]) => ({ keys }),
        removeAutomaticCreationIncludedPropertyKey: (key: ActionStepPropertyKey) => ({ key }),
        addAutomaticCreationIncludedPropertyKey: (key: ActionStepPropertyKey) => ({ key }),
    }),

    connect(() => ({
        values: [
            toolbarConfigLogic,
            ['dataAttributes', 'apiURL', 'temporaryToken', 'buttonVisible', 'userIntent', 'actionId', 'dataAttributes'],
            actionsLogic,
            ['allActions'],
        ],
    })),

    reducers({
        actionFormElementsChains: [
            {} as Record<number, ElementType[]>,
            {
                inspectElementSelected: (state, { element, index }) =>
                    index === null
                        ? []
                        : {
                              ...state,
                              [index]: toElementsChain(element),
                          },
                newAction: (_, { element }) => ({
                    0: element ? toElementsChain(element) : [],
                }),
            },
        ],
        buttonActionsVisible: [
            false,
            {
                showButtonActions: () => true,
                hideButtonActions: () => false,
            },
        ],
        selectedActionId: [
            null as number | 'new' | null,
            {
                selectAction: (_, { id }) => id,
                newAction: () => 'new',
            },
        ],
        newActionForElement: [
            null as HTMLElement | null,
            {
                newAction: (_, { element }) => element,
                selectAction: () => null,
            },
        ],
        inspectingElement: [
            null as number | null,
            {
                inspectForElementWithIndex: (_, { index }) => index,
                inspectElementSelected: () => null,
                selectAction: () => null,
                newAction: () => null,
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
        showActionsTooltip: [
            false,
            {
                setShowActionsTooltip: (_, { showActionsTooltip }) => showActionsTooltip,
            },
        ],
        // we automatically create actions for people from analytics onboarding. This flag controls that experience.
        automaticActionCreationEnabled: [
            false as boolean,
            {
                setAutomaticActionCreationEnabled: (_, { enabled, name }) => (enabled && !!name) || false,
            },
        ],
        newActionName: [
            null as string | null,
            {
                setAutomaticActionCreationEnabled: (_, { enabled, name }) => (enabled && name ? name : null),
            },
        ],
        automaticCreationIncludedPropertyKeys: [
            [] as ActionStepPropertyKey[],
            {
                setAutomaticActionCreationEnabled: (_, { enabled }) =>
                    enabled ? ['text', 'href', 'name', 'selector', 'url'] : [],
                setautomaticCreationIncludedPropertyKeys: (_, { keys }) => keys || [],
                removeAutomaticCreationIncludedPropertyKey: (state, { key }) => state.filter((k) => k !== key),
                addAutomaticCreationIncludedPropertyKey: (state, { key }) =>
                    !state.includes(key) ? [...state, key] : state,
            },
        ],
    }),

    forms(({ values, actions }) => ({
        actionForm: {
            defaults: { name: null, steps: [{}] } as ActionForm,
            errors: ({ name }) => ({
                name: !name || !name.length ? 'Must name this action' : undefined,
            }),
            submit: async (formValues, breakpoint) => {
                const actionToSave = {
                    ...formValues,
                    steps: formValues.steps?.map(stepToDatabaseFormat) || [],
                    creation_context: values.automaticActionCreationEnabled ? 'onboarding' : null,
                }
                const { apiURL, temporaryToken } = values
                const { selectedActionId } = values

                const findUniqueActionName = (baseName: string, index = 0): string => {
                    const proposedName = index === 0 ? baseName : `${baseName} - ${index}`
                    if (!values.allActions.find((action) => action.name === proposedName)) {
                        return proposedName
                    }
                    return findUniqueActionName(baseName, index + 1)
                }

                if (values.newActionName) {
                    // newActionName is programmatically set, but they may already have an existing action with that name. Append an index.
                    actionToSave.name = findUniqueActionName(values.newActionName)
                }

                let response: ActionType
                if (selectedActionId && selectedActionId !== 'new') {
                    response = await api.update(
                        `${apiURL}/api/projects/@current/actions/${selectedActionId}/?temporary_token=${temporaryToken}`,
                        actionToSave
                    )
                } else {
                    response = await api.create(
                        `${apiURL}/api/projects/@current/actions/?temporary_token=${temporaryToken}`,
                        actionToSave
                    )
                }
                breakpoint()

                actions.selectAction(null)
                actionsLogic.actions.updateAction({ action: response })

                if (!values.automaticActionCreationEnabled) {
                    lemonToast.success('Action saved', {
                        button: {
                            label: 'Open in PostHog',
                            action: () => window.open(`${apiURL}${urls.action(response.id)}`, '_blank'),
                        },
                    })
                }

                actions.actionCreatedSuccess(response)
            },

            // whether we show errors after touch (true) or submit (false)
            showErrorsOnTouch: true,
            // show errors even without submitting first
            alwaysShowErrors: false,
        },
    })),

    selectors({
        editingSelectorValue: [
            (s) => [s.editingSelector, s.actionForm],
            (editingSelector, actionForm): string | null => {
                if (editingSelector === null) {
                    return null
                }
                const selector = actionForm.steps?.[editingSelector].selector
                return selector || null
            },
        ],
        elementsChainBeingEdited: [
            (s) => [s.editingSelector, s.actionFormElementsChains],
            (editingSelector, elementChains): ElementType[] => {
                if (editingSelector === null) {
                    return []
                }
                return elementChains[editingSelector] || []
            },
        ],
        selectedAction: [
            (s) => [
                s.selectedActionId,
                s.newActionForElement,
                s.allActions,
                s.dataAttributes,
                s.newActionName,
                s.automaticCreationIncludedPropertyKeys,
            ],
            (
                selectedActionId,
                newActionForElement,
                allActions,
                dataAttributes,
                newActionName,
                automaticCreationIncludedPropertyKeys
            ): ActionType | ActionDraftType | null => {
                if (selectedActionId === 'new') {
                    return newAction(
                        newActionForElement,
                        dataAttributes,
                        newActionName,
                        automaticCreationIncludedPropertyKeys
                    )
                }
                return allActions.find((a) => a.id === selectedActionId) || null
            },
        ],
        isReadyForAutomaticSubmit: [
            (s) => [s.automaticActionCreationEnabled, s.selectedAction, s.actionForm],
            (automaticActionCreationEnabled, selectedAction, actionForm): boolean => {
                return (
                    (automaticActionCreationEnabled &&
                        selectedAction?.name &&
                        actionForm.steps?.[0]?.selector_selected) ||
                    false
                )
            },
        ],
    }),

    subscriptions(({ actions, values }) => ({
        selectedAction: (selectedAction: ActionType | ActionDraftType | null) => {
            if (!selectedAction) {
                actions.setActionFormValues({ name: null, steps: [{}] })
            } else {
                actions.setActionFormValues({
                    ...selectedAction,
                    steps: selectedAction.steps
                        ? selectedAction.steps.map((step) => actionStepToActionStepFormItem(step, false))
                        : [{}],
                })
                if (values.isReadyForAutomaticSubmit) {
                    actions.submitActionForm()
                }
            }
        },
    })),

    listeners(({ actions, values }) => ({
        setElementSelector: ({ selector, index }) => {
            if (values.actionForm) {
                const steps = [...(values.actionForm.steps || [])]
                if (steps && steps[index]) {
                    steps[index].selector = selector
                }
                actions.setActionFormValue('steps', steps)
            }
        },
        selectAction: ({ id }) => {
            if (id) {
                if (!values.buttonVisible) {
                    toolbarConfigLogic.actions.showButton()
                }

                if (!values.buttonActionsVisible) {
                    actions.showButtonActions()
                }

                toolbarLogic.actions.setVisibleMenu('actions')
            }
        },
        inspectElementSelected: ({ element, index }) => {
            if (values.actionForm) {
                const actionStep = actionStepToActionStepFormItem(
                    elementToActionStep(element, values.dataAttributes),
                    true
                )
                const newSteps = (values.actionForm.steps || []).map((step, i) =>
                    // null index implicitly means "new step front of the list"
                    i === (index ?? 0) ? actionStep : step
                )

                actions.setActionFormValue('steps', newSteps)
                actions.incrementCounter()
            }
        },
        showButtonActions: () => {
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'actions', enabled: true })
        },
        hideButtonActions: () => {
            actions.setShowActionsTooltip(false)
            toolbarPosthogJS.capture('toolbar mode triggered', { mode: 'actions', enabled: false })
        },
        [actionsLogic.actionTypes.getActionsSuccess]: () => {
            const { userIntent, actionId } = values
            if (userIntent === 'edit-action') {
                actions.selectAction(actionId)
                toolbarConfigLogic.actions.clearUserIntent()
            } else if (userIntent === 'add-action') {
                actions.newAction()
                toolbarConfigLogic.actions.clearUserIntent()
            } else {
                actions.setShowActionsTooltip(true)
            }
        },
        setShowActionsTooltip: async ({ showActionsTooltip }, breakpoint) => {
            if (showActionsTooltip) {
                await breakpoint(1000)
                actions.setShowActionsTooltip(false)
            }
        },
    })),
])
