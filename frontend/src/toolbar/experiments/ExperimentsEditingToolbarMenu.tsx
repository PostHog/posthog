import { IconPlus, IconRecord, IconTrash, IconDocument, IconEye } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransformField } from '~/toolbar/experiments/WebExperimentTransformField'
import {LemonSlider} from "lib/lemon-ui/LemonSlider";
import {IconWithBadge} from "lib/lemon-ui/icons";


export const ExperimentsEditingToolbarMenu = (): JSX.Element => {
    const { selectedExperimentId, inspectingElement, experimentForm } = useValues(experimentsTabLogic)
    const {
        setExperimentFormValue,
        selectExperiment,
        selectVariant,
        inspectForElementWithIndex,
        addNewVariant,
        addNewElement,
        removeElement,
        removeVariant,
    } = useActions(experimentsTabLogic)

    return (
        <ToolbarMenu>
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
                    <div>
                        <div className="grid grid-cols-3 gap-2 mt-2">
                            {selectedExperimentId === 'new' ? (
                                <EditableField
                                    placeholder="please enter experiment name"
                                    onSave={(newName) => {
                                        experimentForm.name = newName
                                    }}
                                    name="item-name-small"
                                    value={experimentForm.name}
                                />
                            ) : (
                                <h4>{experimentForm.name}</h4>
                            )}
                            <div className='col-span-1'/>
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="col-span-1"
                                sideIcon={<IconPlus/>}
                                onClick={addNewVariant}
                            >
                                Add variant
                            </LemonButton>
                        </div>
                        <Group name="variants">
                            <div>
                                {Object.keys(experimentForm.variants || {}).map((variant, index) => (

                                    <Group key={variant} name={['variants', index]}>
                                        <div className="flex flex-col">
                                            <LemonDivider thick={true}/>
                                            <div className="grid grid-cols-3 gap-2 m-1">
                                                {selectedExperimentId === 'new' && variant !== 'control' ? (
                                                    <EditableField
                                                        onSave={(newName) => {
                                                            if (experimentForm.variants) {
                                                                const webVariant = experimentForm.variants[variant]
                                                                if (webVariant) {
                                                                    experimentForm.variants[newName] = webVariant
                                                                    delete experimentForm.variants[variant]
                                                                    setExperimentFormValue(
                                                                        'variants',
                                                                        experimentForm.variants
                                                                    )
                                                                }
                                                            }
                                                            variant = newName
                                                        }}
                                                        name="item-name-small"
                                                        value={variant}
                                                    />
                                                ) : (
                                                    <h2 className="col-span-1">{variant}</h2>
                                                )}
                                                <div className="col-span-1">
                                                    <IconWithBadge content='50%' status='success'/>
                                                </div>
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    className="col-span-1"
                                                    status="danger"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        removeVariant(variant)
                                                    }}
                                                    sideIcon={<IconTrash/>}
                                                >
                                                    Remove
                                                </LemonButton>
                                            </div>
                                            <LemonDivider dashed={true}/>
                                            <div className="grid grid-cols-3 gap-2 m-1">
                                                <span className="col-span-1">
                                                    <IconDocument/>
                                                    Elements</span>
                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    className="ml-2 col-span-1"
                                                    sideIcon={<IconPlus/>}
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        addNewElement(variant)
                                                    }}
                                                >
                                                    Add element
                                                </LemonButton>

                                                <div className="col-span-1"/>
                                            </div>

                                            <LemonDivider/>
                                            {experimentForm.variants![variant].transforms.map((transform, tIndex) => (
                                                    <div key={tIndex}>
                                                    <span>
                                                        {tIndex + 1} ) {transform.selector ?? 'no element selected'}
                                                    </span>
                                                        <div className="grid grid-cols-3 gap-2 m-1">
                                                            <LemonButton
                                                                size="small"
                                                                className='col-span-1'
                                                                type={
                                                                    inspectingElement === tIndex + 1
                                                                        ? 'primary'
                                                                        : 'secondary'
                                                                }
                                                                onClick={(e) => {
                                                                    e.stopPropagation()
                                                                    selectVariant(variant)
                                                                    inspectForElementWithIndex(
                                                                        variant,
                                                                        inspectingElement === tIndex + 1 ? null : tIndex + 1
                                                                    )
                                                                }}
                                                                icon={<IconRecord/>}
                                                            >
                                                                {transform.selector ? 'Change' : 'Select'}
                                                            </LemonButton>
                                                            <LemonButton
                                                                type="secondary"
                                                                status="danger"
                                                                size="small"
                                                                className='col-span-1'
                                                                onClick={(e) => {
                                                                    e.stopPropagation()
                                                                    removeElement(variant, tIndex)
                                                                }}
                                                                sideIcon={<IconTrash/>}
                                                            >
                                                                Remove
                                                            </LemonButton>
                                                            <div className="col-span-1"/>
                                                        </div>
                                                        <WebExperimentTransformField
                                                            tIndex={tIndex}
                                                            variant={variant}
                                                            transform={transform}
                                                        />
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
