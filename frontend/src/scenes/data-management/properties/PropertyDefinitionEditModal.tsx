import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonModal, LemonSelect, LemonTag } from '@posthog/lemon-ui'

import { PropertyStatusControl } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import type { PropertyDefinitionTypeEnumApi } from '~/generated/core/api.schemas'
import { tagsModel } from '~/models/tagsModel'
import { isCoreFilter } from '~/taxonomy/helpers'

import { PropertyDefinitionEditModalProps, propertyDefinitionEditModalLogic } from './propertyDefinitionEditModalLogic'

const PROPERTY_TYPE_OPTIONS: { label: string; value: PropertyDefinitionTypeEnumApi }[] = [
    { value: 'DateTime', label: 'DateTime' },
    { value: 'String', label: 'String' },
    { value: 'Numeric', label: 'Numeric' },
    { value: 'Boolean', label: 'Boolean' },
]

export function PropertyDefinitionEditModal(props: PropertyDefinitionEditModalProps): JSX.Element {
    const logic = propertyDefinitionEditModalLogic(props)
    const { propertyDefinitionEditFormChanged, isPropertyDefinitionEditFormSubmitting } = useValues(logic)
    const { closeModal, submitPropertyDefinitionEditForm } = useActions(logic)
    const { tags, tagsLoading } = useValues(tagsModel)
    const allowVerification = !isCoreFilter(props.propertyDefinition.name)

    return (
        <LemonModal
            isOpen
            title="Edit definition"
            width={600}
            forceAbovePopovers
            onClose={closeModal}
            hasUnsavedInput={propertyDefinitionEditFormChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeModal}
                        disabledReason={
                            isPropertyDefinitionEditFormSubmitting ? 'Saving property definition' : undefined
                        }
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitPropertyDefinitionEditForm}
                        loading={isPropertyDefinitionEditFormSubmitting}
                        disabledReason={!propertyDefinitionEditFormChanged ? 'No changes to save' : undefined}
                        data-attr="save-property-definition"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={propertyDefinitionEditModalLogic}
                props={props}
                formKey="propertyDefinitionEditForm"
                className="flex flex-col gap-4"
            >
                <div className="flex flex-wrap items-center gap-2 text-secondary">
                    <span>Property name:</span>
                    <LemonTag className="font-mono">{props.propertyDefinition.name}</LemonTag>
                </div>

                <div className="ph-ignore-input">
                    <LemonField name="tags" label="Tags" data-attr="definition-tags">
                        {({ value, onChange }) => (
                            <ObjectTags
                                className="definition-tags"
                                saving={isPropertyDefinitionEditFormSubmitting || tagsLoading}
                                tags={value ?? []}
                                onChange={onChange}
                                tagsAvailable={tags}
                            />
                        )}
                    </LemonField>
                </div>

                <div className="ph-ignore-input">
                    <LemonField name="description" label="Description" data-attr="definition-description">
                        <LemonTextArea />
                    </LemonField>
                </div>

                <div className="ph-ignore-input">
                    <LemonField name="verified" label="Status" data-attr="definition-status">
                        {({ value: verified, onChange }) => (
                            <LemonField name="hidden">
                                {({ value: hidden, onChange: onHiddenChange }) => (
                                    <PropertyStatusControl
                                        isProperty
                                        verified={verified}
                                        hidden={hidden}
                                        showHiddenOption
                                        allowVerification={allowVerification}
                                        onChange={({ verified: newVerified, hidden: newHidden }) => {
                                            onChange(newVerified)
                                            onHiddenChange(newHidden)
                                        }}
                                    />
                                )}
                            </LemonField>
                        )}
                    </LemonField>
                </div>

                <div className="ph-ignore-input">
                    <LemonField name="property_type" label="Property type" data-attr="property-type">
                        {({ value, onChange }) => (
                            <LemonSelect<PropertyDefinitionTypeEnumApi>
                                value={value ?? undefined}
                                onChange={onChange}
                                options={PROPERTY_TYPE_OPTIONS}
                            />
                        )}
                    </LemonField>
                </div>
            </Form>
        </LemonModal>
    )
}
