import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form, Group } from 'kea-forms'
import { IconClose, IconDelete, IconEdit, IconMagnifier, IconMinusOutlined, IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { SelectorEditingModal } from '~/toolbar/actions/SelectorEditingModal'
import { StepField } from '~/toolbar/actions/StepField'
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { posthog } from '~/toolbar/posthog'
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
        <ToolbarMenu>
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
                className="flex flex-col overflow-hidden flex-1"
            >
                <ToolbarMenu.Header>
                    <h1 className="p-1 font-bold text-sm mb-0">
                        {selectedActionId === 'new' ? 'New ' : 'Edit '}
                        action
                    </h1>
                </ToolbarMenu.Header>
                <ToolbarMenu.Body>
                    <div className="p-1">
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
                                <LemonDivider />
                                <div key={index} className="p-1 flex flex-col gap-2">
                                    <div className="flex flex-row justify-between">
                                        <h3>
                                            {index > 0 ? 'OR ' : null}Element #{index + 1}
                                        </h3>
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
                                                inspectForElementWithIndex(inspectingElement === index ? null : index)
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
                                                        If your element is a link, the location that the link opens (
                                                        <code>href</code> tag)
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
                                className="my-2"
                            >
                                Add An Element
                            </LemonButton>
                        ) : null}
                    </div>
                </ToolbarMenu.Body>
                <ToolbarMenu.Footer>
                    <span className="flex-1">
                        <LemonButton
                            type="secondary"
                            status={'muted'}
                            size="small"
                            onClick={() => selectAction(null)}
                            sideIcon={<IconClose />}
                        >
                            Cancel
                        </LemonButton>
                    </span>
                    <LemonButton type="primary" htmlType="submit">
                        {selectedActionId === 'new' ? 'Create ' : 'Save '}
                        action
                    </LemonButton>
                    {selectedActionId !== 'new' ? (
                        <LemonButton type="secondary" status={'danger'} onClick={deleteAction} icon={<IconDelete />} />
                    ) : null}
                </ToolbarMenu.Footer>
            </Form>
        </ToolbarMenu>
    )
}
