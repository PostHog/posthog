import {
    IconAIText,
    IconBug,
    IconCode,
    IconMessage,
    IconPencil,
    IconPlus,
    IconQuestion,
    IconSearch,
    IconTrash
} from '@posthog/icons'
import {
    LemonDivider,
    LemonSegmentedButton,
    LemonSegmentedButtonOption,
    LemonTag,
    LemonTextArea
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form, Group } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { SelectorEditingModal } from '~/toolbar/actions/SelectorEditingModal'
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { elementToQuery } from '~/toolbar/utils'
import {experimentsTabLogic} from "~/toolbar/experiments/experimentsTabLogic";
import {SelectorCount} from "~/toolbar/actions/SelectorCount";
import {StepField} from "~/toolbar/actions/StepField";
import clsx from "clsx";
import {SupportTicketKind} from "lib/components/Support/supportLogic";
import {IconFeedback} from "lib/lemon-ui/icons";
import {LemonField} from "lib/lemon-ui/LemonField";
import {useState} from "react";

type elementTransformKind = 'html' | 'text' | 'css'
const ELEMENT_TRANSFORM_OPTIONS: LemonSegmentedButtonOption<elementTransformKind>[] = [
    {
        value: 'html',
        label: 'HTML',
        icon: <IconCode />,
    },
    {
        value: 'text',
        label: 'Text',
        icon: <IconMessage />,
    },
    {
        value: 'css',
        label: 'CSS',
        icon: <IconAIText />,
    },
]

export const ExperimentsEditingToolbarMenu = (): JSX.Element => {
    const {
        selectedExperimentId,
        inspectingElement,
        editingSelector,
        elementsChainBeingEdited,
        editingSelectorValue,
        experimentForm,
        selectedVariant,
    } = useValues(experimentsTabLogic)
    const {
        setExperimentFormValue,
        selectExperiment,
        selectVariant,
        inspectForElementWithIndex,
        deleteExperiment,
        setElementSelector,
        editSelectorWithIndex,
    } = useActions(experimentsTabLogic)

    const [transformSelected, setTransformSelected] = useState('')

    // const experimentVariants = Object.keys(experimentForm.variants!)
    // console.log(`experimentForm.variants is `, experimentForm.variants)
    // console.log(`Object.keys(experimentForm.variants!) is `, Object.keys(experimentForm.variants!))
    console.log(`experimentForm is `, experimentForm)
    return (
        <ToolbarMenu>
            <SelectorEditingModal
                isOpen={editingSelector !== null}
                setIsOpen={() => editSelectorWithIndex('', null)}
                activeElementChain={elementsChainBeingEdited}
                startingSelector={editingSelectorValue}
                onChange={(selector) => {
                    if (selector && editingSelector !== null) {
                        toolbarPosthogJS.capture('toolbar_manual_selector_applied', {
                            chosenSelector: selector,
                        })
                        setElementSelector(selector, editingSelector)
                    }
                }}
            />
            <Form
                name="experiment"
                logic={experimentsTabLogic}
                formKey="experimentForm"
                enableFormOnSubmit
                className="flex flex-col overflow-hidden flex-1"
            >
                <ToolbarMenu.Header className="border-b">
                    <h1 className="p-1 font-bold text-sm mb-0">
                        {selectedExperimentId === 'new' ? 'New ' : 'Edit '}
                        experiment
                    </h1>
                </ToolbarMenu.Header>
                <ToolbarMenu.Body>
                    <div className="p-1">
                        <div>
                            <p>Name your experiment</p>
                            <Field name="name">
                                <LemonInput
                                    placeholder="E.g: Hero banner redesign"
                                    className="action-title-field"
                                    stopPropagation={true}
                                    value={experimentForm.name}
                                />
                            </Field>
                        </div>
                        <Group name='variants'>
                            <LemonDivider/>
                            <h3> Variants </h3>
                            <div className="mt-2">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    sideIcon={<IconPlus/>}
                                    onClick={() =>
                                        setExperimentFormValue('variants', {
                                            ...experimentForm.variants,
                                            "variant": {
                                                "transforms": []
                                            },
                                    })
                                    }
                                >
                                    Add Another Variant
                                </LemonButton>
                                {Object.keys(experimentForm.variants!).map((variant, index) => (
                                    <Group key={variant} name={['variants', index]}>
                                        <div className="p-1 flex flex-col gap-2">
                                            <h3 className='mb-0'>{variant} </h3>
                                            {/*(Rollout Percentage : {experimentForm.variants![variant].rollout_percentage}% )*/}
                                    <LemonDivider/>
                                            {experimentForm.variants![variant].transforms.map((transform, tIndex) => (
                                                <div key={tIndex}> {transform.selector}
                                                        <div className="action-inspect">
                                                            <LemonButton
                                                                size="small"
                                                                type={inspectingElement === tIndex ? 'primary' : 'secondary'}
                                                                onClick={(e) => {
                                                                    e.stopPropagation()
                                                                    selectVariant(variant)
                                                                    inspectForElementWithIndex(variant, tIndex +1)
                                                                }}
                                                                icon={<IconSearch />}
                                                            >
                                                                {transform.selector ? 'Change Element' : 'Select Element'}
                                                            </LemonButton>
                                                            <LemonSegmentedButton fullWidth options={ELEMENT_TRANSFORM_OPTIONS}

                                                                                  onChange={(e) => setTransformSelected(e)}
                                                            value ={
                                                                transform.html ? "html": transform.text ? "text" : "css"
                                                            }/>
                                                            { transformSelected == 'text' && (
                                                                <LemonTextArea
                                                                    value={transform.text ?? ''}
                                                                    stopPropagation={true}
                                                                />
                                                            )}

                                                            { transformSelected == 'html' && (
                                                                <LemonTextArea
                                                                    value={transform.html ?? ''}
                                                                    stopPropagation={true}
                                                                />
                                                            )}

                                                            { transformSelected == 'css' && (
                                                                <LemonTextArea
                                                                    value={transform.className ?? ''}
                                                                    stopPropagation={true}
                                                                />
                                                            )}

                                                            {inspectingElement === tIndex ? (
                                                                <>
                                                                    {/*<StepField*/}
                                                                    {/*    step={step}*/}
                                                                    {/*    item="selector"*/}
                                                                    {/*    label="Selector"*/}
                                                                    {/*    caption="CSS selector that uniquely identifies your element"*/}
                                                                    {/*/>*/}
                                                                    <div className="flex flex-row justify-end mb-2">
                                                                        <LemonButton
                                                                            size="small"
                                                                            type="secondary"
                                                                            icon={<IconPencil />}
                                                                            onClick={(e) => {
                                                                                e.stopPropagation()
                                                                                toolbarPosthogJS.capture(
                                                                                    'toolbar_manual_selector_modal_opened',
                                                                                    {
                                                                                        selector: transform.selector,
                                                                                    }
                                                                                )
                                                                                editSelectorWithIndex(variant, tIndex)
                                                                            }}
                                                                        >
                                                                            Edit the selector
                                                                        </LemonButton>
                                                                    </div>
                                                                </>
                                                            ): null}
                                                        </div>
                                                   </div>
                                            ))}
                                            </div>
                                    </Group>
                                ))}
                                {/*{ Object.keys(experimentForm.variants!).map (variant) => (*/}
                                {/*    <h3> {variant} </h3>*/}
                                {/*})) }*/}
                            </div>
                        </Group>
                    </div>
                </ToolbarMenu.Body>
                    {/*    { for( const variant in experimentForm.variants?) {*/}
                    {/*        <Group key={variant} name={['variants', variant]}>*/}
                    {/*            <LemonDivider/>*/}
                    {/*            <div key={variant} className="p-1 flex flex-col gap-2">*/}
                    {/*                <div className="flex flex-row justify-between">*/}
                    {/*                    <h3>*/}
                    {/*                        {index > 0 ? 'OR ' : null}Transform #{index + 1}*/}
                    {/*                    </h3>*/}
                    {/*                    <LemonButton*/}
                    {/*                        type="tertiary"*/}
                    {/*                        size="small"*/}
                    {/*                        onClick={() =>*/}
                    {/*                            setExperimentFormValue(*/}
                    {/*                                'variants',*/}
                    {/*                                //experimentForm.variants without the variant at index*/}
                    {/*                                experimentForm.variants?.filter((_, i) => i !== index)*/}
                    {/*                            )*/}
                    {/*                        }*/}
                    {/*                        sideIcon={<IconTrash />}*/}
                    {/*                    >*/}
                    {/*                        Remove*/}
                    {/*                    </LemonButton>*/}
                    {/*                </div>*/}

                    {/*                <div className="action-inspect">*/}
                    {/*                    <LemonButton*/}
                    {/*                        size="small"*/}
                    {/*                        type={inspectingElement === index ? 'primary' : 'secondary'}*/}
                    {/*                        onClick={(e) => {*/}
                    {/*                            e.stopPropagation()*/}
                    {/*                            inspectForElementWithIndex(inspectingElement === index ? null : index)*/}
                    {/*                        }}*/}
                    {/*                        icon={<IconSearch />}*/}
                    {/*                    >*/}
                    {/*                        {'Select Element'}*/}
                    {/*                    </LemonButton>*/}
                    {/*                </div>*/}

                    {/*                {variant?.event === '$autocapture' || inspectingElement === index ? (*/}
                    {/*                    <>*/}
                    {/*                        <StepField*/}
                    {/*                            variant={variant}*/}
                    {/*                            item="selector"*/}
                    {/*                            label="Selector"*/}
                    {/*                            caption="CSS selector that uniquely identifies your element"*/}
                    {/*                        />*/}
                    {/*                        <div className="flex flex-row justify-end mb-2">*/}
                    {/*                            <LemonButton*/}
                    {/*                                size="small"*/}
                    {/*                                type="secondary"*/}
                    {/*                                icon={<IconPencil />}*/}
                    {/*                                onClick={(e) => {*/}
                    {/*                                    e.stopPropagation()*/}
                    {/*                                    toolbarPosthogJS.capture(*/}
                    {/*                                        'toolbar_manual_selector_modal_opened',*/}
                    {/*                                        {*/}
                    {/*                                            selector: variant?.selector,*/}
                    {/*                                        }*/}
                    {/*                                    )*/}
                    {/*                                    editSelectorWithIndex(index)*/}
                    {/*                                }}*/}
                    {/*                            >*/}
                    {/*                                Edit the selector*/}
                    {/*                            </LemonButton>*/}
                    {/*                        </div>*/}
                    {/*                        <StepField*/}
                    {/*                            variant={variant}*/}
                    {/*                            item="href"*/}
                    {/*                            label="Link target"*/}
                    {/*                            caption={*/}
                    {/*                                <>*/}
                    {/*                                    If your element is a link, the location that the link opens (*/}
                    {/*                                    <code>href</code> tag)*/}
                    {/*                                </>*/}
                    {/*                            }*/}
                    {/*                        />*/}
                    {/*                        <LemonTag type="highlight">*/}
                    {/*                            <span className="uppercase">and</span>*/}
                    {/*                        </LemonTag>*/}
                    {/*                        <StepField*/}
                    {/*                            variant={variant}*/}
                    {/*                            item="text"*/}
                    {/*                            label="Text"*/}
                    {/*                            caption="Text content inside your element"*/}
                    {/*                        />*/}
                    {/*                        <LemonTag type="highlight">*/}
                    {/*                            <span className="uppercase">and</span>*/}
                    {/*                        </LemonTag>*/}
                    {/*                        <StepField*/}
                    {/*                            variant={variant}*/}
                    {/*                            item="url"*/}
                    {/*                            label="Page URL"*/}
                    {/*                            caption="Elements will match only when triggered from the URL."*/}
                    {/*                        />*/}
                    {/*                    </>*/}
                    {/*                ) : null}*/}

                    {/*                {index === (experimentForm.variants?.length || 0) - 1 ? (*/}
                    {/*                    <div className="text-right mt-4">*/}
                    {/*                        <LemonButton*/}
                    {/*                            type="secondary"*/}
                    {/*                            size="small"*/}
                    {/*                            sideIcon={<IconPlus />}*/}
                    {/*                            onClick={() =>*/}
                    {/*                                setExperimentFormValue('variants', [...(experimentForm.variants || []), {}])*/}
                    {/*                            }*/}
                    {/*                        >*/}
                    {/*                            Add Another Element*/}
                    {/*                        </LemonButton>*/}
                    {/*                    </div>*/}
                    {/*                ) : null}*/}
                    {/*            </div>*/}
                    {/*        </Group>*/}
                    {/*    ))}*/}

                    {/*    {(experimentForm.variants || []).length === 0 ? (*/}
                    {/*        <LemonButton*/}
                    {/*            icon={<IconPlus />}*/}
                    {/*            size="small"*/}
                    {/*            type="primary"*/}
                    {/*            onClick={() => setExperimentFormValue('variants', [...(experimentForm.variants || []), {}])}*/}
                    {/*            className="my-2"*/}
                    {/*        >*/}
                    {/*            Add An Element*/}
                    {/*        </LemonButton>*/}
                    {/*    ) : null}*/}
                    {/*</div>*/}
                {/*</ToolbarMenu.Body>*/}
                <ToolbarMenu.Footer>
                    <span className="flex-1">
                        {selectedExperimentId !== 'new' ? (
                            <LemonButton
                                type="secondary"
                                status="danger"
                                onClick={deleteExperiment}
                                icon={<IconTrash />}
                                size="small"
                            >
                                Delete
                            </LemonButton>
                        ) : null}
                    </span>
                    <LemonButton type="secondary" size="small" onClick={() => selectExperiment(null)}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" htmlType="submit" size="small">
                        {selectedExperimentId === 'new' ? 'Create ' : 'Save '}
                        experiment
                    </LemonButton>
                </ToolbarMenu.Footer>
            </Form>
        </ToolbarMenu>
    )
}
