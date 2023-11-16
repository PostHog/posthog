import { ToolbarMenu } from '~/toolbar/button/ToolbarMenu'

import { IconClose, IconDelete, IconEdit, IconMagnifier, IconMinusOutlined, IconPlus } from 'lib/lemon-ui/icons'
import { useActions, useValues } from 'kea'
import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { SelectorEditingModal } from '~/toolbar/elements/SelectorEditingModal'
import { posthog } from '~/toolbar/posthog'
import { Field, Form, Group } from 'kea-forms'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { StepField } from '~/toolbar/actions/StepField'
import { getShadowRootPopoverContainer } from '~/toolbar/utils'

export const ActionsEditingToolbarMenu = (): JSX.Element => {
    const {
        selectedActionId,
        inspectingElement,
        editingSelector,
        elementsChainBeingEdited,
        editingSelectorValue,
        actionForm,
    } = useValues(actionsTabLogic)
    const {
        setActionFormValue,
        selectAction,
        inspectForElementWithIndex,
        deleteAction,
        setElementSelector,
        editSelectorWithIndex,
    } = useActions(actionsTabLogic)

    return (
        <>
            <SelectorEditingModal
                isOpen={editingSelector !== null}
                setIsOpen={() => editSelectorWithIndex(null)}
                activeElementChain={elementsChainBeingEdited}
                startingSelector={editingSelectorValue}
                onChange={(selector) => {
                    if (selector && editingSelector !== null) {
                        posthog.capture('toolbar_manual_selector_applied', {
                            chosenSelector: selector,
                        })
                        setElementSelector(selector, editingSelector)
                    }
                }}
            />
            <Form
                name="action_step"
                logic={actionsTabLogic}
                formKey={'actionForm'}
                enableFormOnSubmit
                className={'flex flex-col h-full gap-2'}
            >
                <ToolbarMenu
                    header={
                        <>
                            <div className={'flex flex-row items-center justify-between px-1 pt-1'}>
                                <h1 className="uppercase font-bold text-sm mb-0">
                                    {selectedActionId === 'new' ? 'New ' : 'Edit '}
                                    action
                                </h1>
                                <LemonButton
                                    type="secondary"
                                    status={'muted'}
                                    size="small"
                                    onClick={() => selectAction(null)}
                                    sideIcon={<IconClose />}
                                >
                                    Cancel
                                </LemonButton>
                            </div>
                        </>
                    }
                    body={
                        <>
                            <div>
                                <p>What did your user do?</p>
                                <Field name="name">
                                    <LemonInput
                                        placeholder="E.g: Clicked Sign Up"
                                        className="action-title-field"
                                        stopPropagation={true}
                                    />
                                </Field>
                            </div>

                            {actionForm.steps?.map((step, index) => (
                                <Group key={index} name={['steps', index]}>
                                    <div key={index} className="action-section p-1 highlight flex flex-col gap-2">
                                        <div className="flex flex-row justify-between">
                                            <h1 className="section-title">
                                                {index > 0 ? 'OR ' : null}Element #{index + 1}
                                            </h1>
                                            <LemonButton
                                                type={'tertiary'}
                                                status={'muted'}
                                                size="small"
                                                onClick={() =>
                                                    setActionFormValue(
                                                        'steps',
                                                        //actionForm.steps without the step at index
                                                        actionForm.steps?.filter((_, i) => i !== index)
                                                    )
                                                }
                                                sideIcon={<IconMinusOutlined />}
                                            >
                                                Remove
                                            </LemonButton>
                                        </div>

                                        <div className="action-inspect">
                                            <LemonButton
                                                size="small"
                                                type={inspectingElement === index ? 'primary' : 'secondary'}
                                                onClick={(e) => {
                                                    e.stopPropagation()
                                                    inspectForElementWithIndex(
                                                        inspectingElement === index ? null : index
                                                    )
                                                }}
                                                icon={<IconMagnifier />}
                                            >
                                                {step?.event === '$autocapture' ? 'Change Element' : 'Select Element'}
                                            </LemonButton>
                                        </div>

                                        {step?.event === '$autocapture' || inspectingElement === index ? (
                                            <>
                                                <StepField
                                                    step={step}
                                                    item="selector"
                                                    label="Selector"
                                                    caption="CSS selector that uniquely identifies your element"
                                                />
                                                <div className="flex flex-row justify-end mb-2">
                                                    <LemonButton
                                                        size={'small'}
                                                        type={'secondary'}
                                                        icon={<IconEdit />}
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            posthog.capture('toolbar_manual_selector_modal_opened', {
                                                                selector: step?.selector,
                                                            })
                                                            editSelectorWithIndex(index)
                                                        }}
                                                        getTooltipPopupContainer={getShadowRootPopoverContainer}
                                                    >
                                                        Edit the selector
                                                    </LemonButton>
                                                </div>
                                                <StepField
                                                    step={step}
                                                    item="href"
                                                    label="Link target"
                                                    caption={
                                                        <>
                                                            If your element is a link, the location that the link opens
                                                            (<code>href</code> tag)
                                                        </>
                                                    }
                                                />
                                                <StepField
                                                    step={step}
                                                    item="text"
                                                    label="Text"
                                                    caption="Text content inside your element"
                                                />

                                                <StepField
                                                    step={step}
                                                    item="url"
                                                    label="Page URL"
                                                    caption="Elements will match only when triggered from the URL."
                                                />
                                            </>
                                        ) : null}

                                        {index === (actionForm.steps?.length || 0) - 1 ? (
                                            <div className={'text-right mt-4'}>
                                                <LemonButton
                                                    type="secondary"
                                                    status={'muted'}
                                                    size="small"
                                                    sideIcon={<IconPlus />}
                                                    onClick={() =>
                                                        setActionFormValue('steps', [...(actionForm.steps || []), {}])
                                                    }
                                                >
                                                    Add Another Element
                                                </LemonButton>
                                            </div>
                                        ) : null}
                                    </div>
                                </Group>
                            ))}

                            {(actionForm.steps || []).length === 0 ? (
                                <LemonButton
                                    icon={<IconPlus />}
                                    size="small"
                                    type="primary"
                                    onClick={() => setActionFormValue('steps', [...(actionForm.steps || []), {}])}
                                >
                                    Add An Element
                                </LemonButton>
                            ) : null}
                        </>
                    }
                    footer={
                        <div className={'flex flex-row w-full justify-between px-2 pb-1'}>
                            <LemonButton type="primary" htmlType="submit">
                                {selectedActionId === 'new' ? 'Create ' : 'Save '}
                                action
                            </LemonButton>
                            {selectedActionId !== 'new' ? (
                                <LemonButton
                                    type="secondary"
                                    status={'danger'}
                                    onClick={deleteAction}
                                    icon={<IconDelete />}
                                />
                            ) : null}
                        </div>
                    }
                />
            </Form>
        </>
    )
}
