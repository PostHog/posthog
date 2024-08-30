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
import clsx from "clsx";
import { useActions, useValues } from 'kea'
import { Field, Form, Group } from 'kea-forms'
import {SupportTicketKind} from "lib/components/Support/supportLogic";
import {IconFeedback} from "lib/lemon-ui/icons";
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import {LemonField} from "lib/lemon-ui/LemonField";
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import {useState} from "react";

import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import {SelectorCount} from "~/toolbar/actions/SelectorCount";
import { SelectorEditingModal } from '~/toolbar/actions/SelectorEditingModal'
import {StepField} from "~/toolbar/actions/StepField";
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import {experimentsTabLogic} from "~/toolbar/experiments/experimentsTabLogic";
import {WebExperimentTransformField} from "~/toolbar/experiments/WebExperimentTransformField";
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import {WebExperimentTransform} from "~/toolbar/types";
import { elementToQuery } from '~/toolbar/utils'

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
                                    onClick={() => {
                                        if (experimentForm.variants) {
                                            const nextVariantName = `variant #${Object.keys(experimentForm.variants).length}`
                                            experimentForm.variants[nextVariantName] = {
                                                transforms: [],
                                                conditions: null,
                                            }
                                        }

                                        setExperimentFormValue('variants', experimentForm.variants)
                                    }}
                                >
                                    Add Another Variant
                                </LemonButton>
                                {Object.keys(experimentForm.variants!).map((variant, index) => (
                                    <Group key={variant} name={['variants', index]}>
                                        <div className="p-1 flex flex-col gap-2">
                                            <h3 className='mb-0'>{variant} </h3>
                                             <LemonButton
                                    type="secondary"
                                    size="small"
                                    sideIcon={<IconPlus/>}
                                    onClick={() => {
                                        if (experimentForm.variants) {
                                            const webVariant = experimentForm.variants[variant]
                                            if (webVariant) {
                                                if (webVariant.transforms) {
                                                    webVariant.transforms.push({
                                                     text: "Enter text here",
                                                     html: "Enter HTML here",
                                                    } as unknown as WebExperimentTransform)
                                                }
                                            }
                                            setExperimentFormValue('variants', experimentForm.variants)
                                    }}}
                                >
                                    Add Another Element
                                </LemonButton>
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
                                                                    console.log(`calling inspectForElementWithIndex(${variant}, ${tIndex +1})`)
                                                                    inspectForElementWithIndex(variant, tIndex +1)
                                                                }}
                                                                icon={<IconSearch />}
                                                            >
                                                                {transform.selector ? 'Change Element' : 'Select Element'}
                                                            </LemonButton>
                                                            <WebExperimentTransformField tIndex={tIndex} variant={variant} transform={transform} />

                                                            {inspectingElement === tIndex ? (
                                                                <>
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
                            </div>
                        </Group>
                    </div>
                </ToolbarMenu.Body>
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
