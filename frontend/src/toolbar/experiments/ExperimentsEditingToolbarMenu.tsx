import { IconPlus, IconSearch, IconTrash } from '@posthog/icons'
import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form, Group } from 'kea-forms'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { experimentsTabLogic } from '~/toolbar/experiments/experimentsTabLogic'
import { WebExperimentTransformField } from '~/toolbar/experiments/WebExperimentTransformField'

export const ExperimentsEditingToolbarMenu = (): JSX.Element => {
    const { selectedExperimentId, inspectingElement, experimentForm } = useValues(experimentsTabLogic)
    const {
        setExperimentFormValue,
        selectExperiment,
        selectVariant,
        inspectForElementWithIndex,
        deleteExperiment,
        newVariant,
        newElement,
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
                        <div className="flex">
                            {selectedExperimentId === 'new' ? (
                                <EditableField
                                    onSave={(newName) => {
                                        experimentForm.name = newName
                                    }}
                                    name="item-name-small"
                                    value={experimentForm.name}
                                />
                            ) : (
                                <h4>{experimentForm.name}</h4>
                            )}
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="ml-3"
                                sideIcon={<IconPlus />}
                                onClick={newVariant}
                            >
                                Add Variant
                            </LemonButton>
                        </div>
                        <Group name="variants">
                            <LemonDivider />

                            <div className="mt-2">
                                {Object.keys(experimentForm.variants || {}).map((variant, index) => (
                                    <Group key={variant} name={['variants', index]}>
                                        <div className="flex flex-col">
                                            {selectedExperimentId === 'new' ? (
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
                                                <h3 className="mb-0">{variant}</h3>
                                            )}
                                            <div className="flex p-1 flex-col-4">
                                                <span>
                                                    (rollout percentage :{' '}
                                                    {experimentForm.variants && experimentForm.variants[variant]
                                                        ? experimentForm.variants[variant].rollout_percentage
                                                        : 0}{' '}
                                                    )
                                                </span>

                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    className="ml-2"
                                                    sideIcon={<IconPlus />}
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        newElement(variant)
                                                    }}
                                                >
                                                    Add Element
                                                </LemonButton>

                                                <LemonButton
                                                    type="secondary"
                                                    size="small"
                                                    className="ml-2"
                                                    onClick={(e) => {
                                                        e.stopPropagation()
                                                        removeVariant(variant)
                                                    }}
                                                    sideIcon={<IconTrash />}
                                                >
                                                    Remove
                                                </LemonButton>
                                            </div>

                                            <LemonDivider />
                                            {experimentForm.variants![variant].transforms.map((transform, tIndex) => (
                                                <div key={tIndex}>
                                                    <span>
                                                        {tIndex + 1} ) {transform.selector}
                                                    </span>
                                                    <div className="flex p-1 flex-col-3">
                                                        <LemonButton
                                                            size="small"
                                                            type={
                                                                inspectingElement === tIndex + 1
                                                                    ? 'primary'
                                                                    : 'tertiary'
                                                            }
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                selectVariant(variant)
                                                                inspectForElementWithIndex(
                                                                    variant,
                                                                    inspectingElement === tIndex + 1 ? null : tIndex + 1
                                                                )
                                                            }}
                                                            icon={<IconSearch />}
                                                        >
                                                            {transform.selector ? 'Change Element' : 'Select Element'}
                                                        </LemonButton>
                                                        <LemonButton
                                                            type="tertiary"
                                                            size="small"
                                                            className="ml-2"
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                removeElement(variant, tIndex)
                                                            }}
                                                            sideIcon={<IconTrash />}
                                                        >
                                                            Remove
                                                        </LemonButton>
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
