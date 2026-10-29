import { useActions, useValues } from 'kea'
import { Field, Form, Group } from 'kea-forms'

import { IconArrowLeft, IconPlus } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'

import { ActionStepEditor } from '~/toolbar/shared/actions/ActionStepEditor'
import { SelectorEditingModal } from '~/toolbar/shared/actions/SelectorEditingModal'
import { urls } from '~/toolbar/shared/urls'

import { extensionActionsLogic } from '../../logics/panel/extensionActionsLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'

export function ExtensionActionEditor(): JSX.Element | null {
    const { actionsState, actionForm, editingSelector, saving } = useValues(extensionActionsLogic)
    const { selectAction, inspectForStep, setActionFormValue, setEditingSelector, applySelector } =
        useActions(extensionActionsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)

    if (!actionsState || actionsState.selectedActionId === null) {
        return null
    }
    const { selectedActionId, inspectingElement, actionFormElementsChains, saveResult } = actionsState
    const steps = actionForm.steps ?? []
    const isNew = selectedActionId === 'new'

    return (
        <>
            <SelectorEditingModal
                isOpen={editingSelector !== null}
                setIsOpen={() => setEditingSelector(null)}
                activeElementChain={editingSelector !== null ? (actionFormElementsChains[editingSelector] ?? []) : []}
                startingSelector={editingSelector !== null ? steps[editingSelector]?.selector : null}
                checkUniqueness={false}
                onChange={(selector) => {
                    if (selector && editingSelector !== null) {
                        applySelector(editingSelector, selector)
                    }
                }}
            />
            <Form logic={extensionActionsLogic} formKey="actionForm" enableFormOnSubmit className="flex flex-col gap-2">
                <div className="flex items-center gap-1">
                    <LemonButton
                        size="small"
                        icon={<IconArrowLeft />}
                        tooltip="Back to the actions"
                        onClick={() => selectAction(null)}
                        data-attr="toolbar-extension-action-back"
                    />
                    <span className="font-semibold flex-1">{isNew ? 'New action' : 'Edit action'}</span>
                    {!isNew && (
                        <Link to={projectUrl(urls.action(selectedActionId))} target="_blank" className="text-xs">
                            Open in PostHog <IconOpenInNew />
                        </Link>
                    )}
                </div>
                {saveResult?.status === 'failed' && (
                    <LemonBanner type="error">Couldn't save the action: {saveResult.error}</LemonBanner>
                )}
                <Field name="name" label="What did your user do?">
                    <LemonInput placeholder="For example: Clicked sign up" data-attr="toolbar-extension-action-name" />
                </Field>
                {steps.map((step, index) => (
                    <Group key={index} name={['steps', index]}>
                        <LemonDivider className="my-1" />
                        <div className="flex flex-col gap-2">
                            <ActionStepEditor
                                step={step}
                                index={index}
                                inspecting={inspectingElement === index}
                                onInspect={() => inspectForStep(inspectingElement === index ? null : index)}
                                onEditSelector={() => setEditingSelector(index)}
                                onRemove={() =>
                                    setActionFormValue(
                                        'steps',
                                        steps.filter((_, i) => i !== index)
                                    )
                                }
                            />
                        </div>
                    </Group>
                ))}
                <LemonButton
                    size="small"
                    type="secondary"
                    icon={<IconPlus />}
                    onClick={() => setActionFormValue('steps', [...steps, {}])}
                    data-attr="toolbar-extension-action-add-step"
                >
                    {steps.length === 0 ? 'Add an element' : 'Add another element'}
                </LemonButton>
                <LemonDivider className="my-1" />
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <LemonButton
                        size="small"
                        type="secondary"
                        onClick={() => selectAction(null)}
                        data-attr="toolbar-extension-action-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        size="small"
                        type="primary"
                        htmlType="submit"
                        loading={saving}
                        data-attr="toolbar-extension-action-save"
                    >
                        {isNew ? 'Create action' : 'Save action'}
                    </LemonButton>
                </div>
            </Form>
        </>
    )
}
