import { kea } from 'kea'
import api from 'lib/api'
import { actionsLogic } from '~/toolbar/actions/actionsLogic'
import { actionStepToAntdForm, elementToActionStep, stepToDatabaseFormat } from '~/toolbar/utils'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'
import type { actionsTabLogicType } from './actionsTabLogicType'
import { ActionType, ElementType } from '~/types'
import { ActionDraftType, ActionForm, AntdFieldData } from '~/toolbar/types'
import { FormInstance } from 'antd/lib/form'
import { posthog } from '~/toolbar/posthog'
import { lemonToast } from 'lib/lemon-ui/lemonToast'
import { urls } from 'scenes/urls'

function newAction(element: HTMLElement | null, dataAttributes: string[] = []): ActionDraftType {
    return {
        name: '',
        steps: [element ? actionStepToAntdForm(elementToActionStep(element, dataAttributes), true) : {}],
    }
}

function toElementsChain(element: HTMLElement): ElementType[] {
    const chain: HTMLElement[] = []
    let currentElement: HTMLElement | null | undefined = element
    while (currentElement && chain.length <= 10 && currentElement !== document.body) {
        chain.push(currentElement)
        currentElement = currentElement.parentElement
    }
    return chain.map(
        (element, index) =>
            ({
                attr_class: element.getAttribute('class') || undefined,
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

export type ActionFormInstance = FormInstance<ActionForm>

export const actionsTabLogic = kea<actionsTabLogicType>({
    path: ['toolbar', 'actions', 'actionsTabLogic'],
    actions: {
        setForm: (form: ActionFormInstance) => ({ form }),
        selectAction: (id: number | null) => ({ id: id || null }),
        newAction: (element?: HTMLElement) => ({
            element: element || null,
        }),
        inspectForElementWithIndex: (index: number | null) => ({ index }),
        editSelectorWithIndex: (index: number | null) => ({ index }),
        inspectElementSelected: (element: HTMLElement, index: number | null) => ({ element, index }),
        setEditingFields: (editingFields: AntdFieldData[]) => ({ editingFields }),
        incrementCounter: true,
        saveAction: (formValues: ActionForm) => ({ formValues }),
        deleteAction: true,
        showButtonActions: true,
        hideButtonActions: true,
        setShowActionsTooltip: (showActionsTooltip: boolean) => ({ showActionsTooltip }),
        setElementSelector: (selector: string, index: number) => ({ selector, index }),
    },

    reducers: {
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
        editingFields: [
            null as AntdFieldData[] | null,
            {
                setEditingFields: (_, { editingFields }) => editingFields,
                selectAction: () => null,
                newAction: () => null,
            },
        ],
        form: [
            null as ActionFormInstance | null,
            {
                setForm: (_, { form }) => form,
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
    },

    selectors: {
        elementsChainBeingEdited: [
            (s) => [s.editingSelector, s.actionFormElementsChains],
            (editingSelector, elementChains): ElementType[] => {
                if (editingSelector === null) {
                    return []
                } else {
                    return elementChains[editingSelector] || []
                }
            },
        ],
        selectedAction: [
            (s) => [s.selectedActionId, s.newActionForElement, actionsLogic.selectors.allActions],
            (selectedActionId, newActionForElement, allActions): ActionType | ActionDraftType | null => {
                if (selectedActionId === 'new') {
                    return newAction(newActionForElement, [])
                }
                return allActions.find((a) => a.id === selectedActionId) || null
            },
        ],
        initialValuesForForm: [
            (s) => [s.selectedAction],
            (selectedAction): Partial<ActionForm> =>
                selectedAction
                    ? {
                          ...selectedAction,
                          steps: selectedAction.steps?.map((step) => actionStepToAntdForm(step)) || [],
                      }
                    : { name: '', steps: [] },
        ],
        selectedEditedAction: [
            // `editingFields` don't update on values.form.setFields(fields), so reloading by tagging a few other selectors
            (s) => [s.selectedAction, s.initialValuesForForm, s.form, s.editingFields, s.inspectingElement, s.counter],
            (selectedAction, initialValuesForForm, form): ActionForm => {
                return selectedAction ? { ...initialValuesForForm, ...(form?.getFieldValue('') || {}) } : null
            },
        ],
    },

    listeners: ({ actions, values }) => ({
        setElementSelector: ({ selector, index }) => {
            if (values.form) {
                const fieldsValue = { ...values.form.getFieldsValue() }
                const steps = fieldsValue.steps
                if (steps && steps[index]) {
                    steps[index].selector = selector
                }
                values.form.setFieldsValue(fieldsValue)
            }
        },
        selectAction: ({ id }) => {
            if (id) {
                if (!toolbarLogic.values.buttonVisible) {
                    toolbarLogic.actions.showButton()
                }

                if (!values.buttonActionsVisible) {
                    actions.showButtonActions()
                }
                if (!toolbarButtonLogic.values.actionsInfoVisible) {
                    toolbarButtonLogic.actions.showActionsInfo()
                }
            }
        },
        inspectElementSelected: ({ element, index }) => {
            if (values.form) {
                const actionStep = actionStepToAntdForm(
                    elementToActionStep(element, toolbarLogic.values.dataAttributes),
                    true
                )
                const fields = Object.entries(actionStep).map(([key, value]) => {
                    return { name: ['steps', index || 0, key], value }
                })
                values.form.setFields(fields)
                actions.incrementCounter()
            }
        },
        saveAction: async ({ formValues }, breakpoint) => {
            const actionToSave = {
                ...formValues,
                steps: formValues.steps?.map(stepToDatabaseFormat) || [],
            }
            const { apiURL, temporaryToken } = toolbarLogic.values
            const { selectedActionId } = values

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

            actionsLogic.actions.updateAction({ action: response })
            actions.selectAction(null)

            lemonToast.success('Action saved', {
                button: {
                    label: 'Open in PostHog',
                    action: () => window.open(`${apiURL}${urls.action(response.id)}`, '_blank'),
                },
            })
        },
        deleteAction: async () => {
            const { apiURL, temporaryToken } = toolbarLogic.values
            const { selectedActionId } = values
            if (selectedActionId && selectedActionId !== 'new') {
                await api.delete(
                    `${apiURL}/api/projects/@current/actions/${selectedActionId}/?temporary_token=${temporaryToken}`
                )
                actionsLogic.actions.deleteAction({ id: selectedActionId })
                actions.selectAction(null)
                lemonToast.info('Action deleted')
            }
        },
        showButtonActions: () => {
            actionsLogic.actions.getActions()
            posthog.capture('toolbar mode triggered', { mode: 'actions', enabled: true })
        },
        hideButtonActions: () => {
            actions.setShowActionsTooltip(false)
            posthog.capture('toolbar mode triggered', { mode: 'actions', enabled: false })
        },
        [actionsLogic.actionTypes.getActionsSuccess]: () => {
            const { userIntent } = toolbarLogic.values
            if (userIntent === 'edit-action') {
                actions.selectAction(toolbarLogic.values.actionId)
                toolbarLogic.actions.clearUserIntent()
            } else if (userIntent === 'add-action') {
                actions.newAction()
                toolbarLogic.actions.clearUserIntent()
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
    }),
})
