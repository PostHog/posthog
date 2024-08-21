import { IconPencil, IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import { LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Field, Form, Group } from 'kea-forms'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { actionsTabLogic } from '~/toolbar/actions/actionsTabLogic'
import { SelectorEditingModal } from '~/toolbar/actions/SelectorEditingModal'
import { StepField } from '~/toolbar/actions/StepField'
import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import {experimentsTabLogic} from "~/toolbar/experiments/experimentsTabLogic";

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
        inspectForElementWithIndex,
        deleteExperiment,
        setElementSelector,
        editSelectorWithIndex,
    } = useActions(experimentsTabLogic)

    const experimentVariants = Object.keys(experimentForm.variants!)
    console.log(`experimentForm.variants is `, experimentForm.variants)
    console.log(`Object.keys(experimentForm.variants!) is `, Object.keys(experimentForm.variants!))

    return (
        <ToolbarMenu>
            <SelectorEditingModal
                isOpen={editingSelector !== null}
                setIsOpen={() => editSelectorWithIndex(null)}
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
                name="action_variant"
                logic={actionsTabLogic}
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
                            <div className="text-right mt-4">
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    sideIcon={<IconPlus/>}
                                    onClick={() =>
                                        setExperimentFormValue('variants', [...(experimentForm.variants || {}), {}])
                                    }
                                >
                                    Add Another Variant
                                </LemonButton>
                                {/*{ experimentVariants.forEach((variant)=> {*/}
                                {/*    <>*/}
                                {/*        <h3> {variant} </h3>*/}
                                {/*    </>*/}
                                {/*})}*/}
                                {Object.keys(experimentForm.variants!).map((variant, index) => (
                                    <Group key={variant} name={['variants', index]}>
                                        <div className="p-1 flex flex-col gap-2">
                                    <h3>{variant}</h3>
                                    <LemonDivider/>
                                        <table>
                                            <thead>
                                            <th>Selector</th>
                                            <th>text</th>
                                            <th>html</th>
                                            <th>imgUrl</th>
                                            <th>className</th>
                                            </thead>
                                            {experimentForm.variants![variant].transforms.map((transform, tIndex) => (
                                                <tr key={tIndex}>
                                                    <td>{transform.selector}</td>
                                                    <td><LemonInput
                                    placeholder="E.g. some text here"
                                    className="action-title-field"
                                    stopPropagation={true}
                                    value={transform.text}
                                /></td>
                                                    <td><LemonInput
                                    placeholder="E.g. some html here"
                                    className="action-title-field"
                                    stopPropagation={true}
                                    value={transform.html}
                                /></td>
                                                    <td>
                                                        <LemonInput
                                                            placeholder="E.g. some imgUrl here"
                                                            className="action-title-field"
                                                            stopPropagation={true}
                                                            value={transform.imgUrl}
                                                        />
                                                    </td>
                                                    <td>
                                                        <LemonInput
                                                            placeholder="E.g. some className here"
                                                            className="action-title-field"
                                                            stopPropagation={true}
                                                            value={transform.className}
                                                        />
                                                    </td>
                                                </tr>
                                            ))}
                                        </table>
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
                        action
                    </LemonButton>
                </ToolbarMenu.Footer>
            </Form>
        </ToolbarMenu>
    )
}
