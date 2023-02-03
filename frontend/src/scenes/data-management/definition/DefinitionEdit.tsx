import { PageHeader } from 'lib/components/PageHeader'
import { DefinitionPageMode } from 'scenes/data-management/definition/definitionLogic'
import { useActions, useValues } from 'kea'
import { definitionEditLogic, DefinitionEditLogicProps } from 'scenes/data-management/definition/definitionEditLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Field } from 'lib/forms/Field'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { getPropertyLabel, isPostHogProp } from 'lib/components/PropertyKeyInfo'
import { VerifiedEventCheckbox } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { Form } from 'kea-forms'
import { tagsModel } from '~/models/tagsModel'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'

export function DefinitionEdit(props: DefinitionEditLogicProps): JSX.Element {
    const logic = definitionEditLogic(props)
    const { definitionLoading, definition, hasTaxonomyFeatures, isEvent } = useValues(logic)
    const { setPageMode, saveDefinition } = useActions(logic)
    const { tags, tagsLoading } = useValues(tagsModel)

    return (
        <Form logic={definitionEditLogic} props={props} formKey="definition">
            <PageHeader
                title="Edit event"
                buttons={
                    <>
                        <LemonButton
                            data-attr="cancel-definition"
                            type="secondary"
                            onClick={() => {
                                setPageMode(DefinitionPageMode.View)
                            }}
                            disabled={definitionLoading}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            data-attr="save-definition"
                            type="primary"
                            onClick={() => {
                                saveDefinition({})
                            }}
                            disabled={definitionLoading}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            />
            <LemonDivider />
            <div className={'DefinitionEdit--form my-4'}>
                <div>
                    <h1>{getPropertyLabel(definition.name) || ''}</h1>
                    <div className="definition-sent-as flex-wrap">
                        <div>Raw event name:</div>
                        <div>
                            <pre>{definition.name}</pre>
                        </div>
                    </div>
                </div>
                {hasTaxonomyFeatures && (
                    <div className="mt-4 ph-ignore-input">
                        <Field name="description" label="Description" data-attr="definition-description">
                            <LemonTextArea value={definition.description} />
                        </Field>
                    </div>
                )}
                {hasTaxonomyFeatures && isEvent && !isPostHogProp(definition.name) && 'verified' in definition && (
                    <div className="mt-4 ph-ignore-input">
                        <Field name="verified" data-attr="definition-verified">
                            {({ value, onChange }) => (
                                <VerifiedEventCheckbox
                                    verified={!!value}
                                    onChange={(nextVerified) => {
                                        onChange(nextVerified)
                                    }}
                                />
                            )}
                        </Field>
                    </div>
                )}
                {hasTaxonomyFeatures && 'tags' in definition && (
                    <div className="mt-4 ph-ignore-input">
                        <Field name="tags" label="Tags" data-attr="definition-tags">
                            {({ value, onChange }) => (
                                <ObjectTags
                                    className="definition-tags"
                                    saving={definitionLoading || tagsLoading}
                                    tags={value || []}
                                    onChange={(_, tags) => onChange(tags)}
                                    style={{ marginBottom: 4 }}
                                    tagsAvailable={tags}
                                />
                            )}
                        </Field>
                    </div>
                )}
                {hasTaxonomyFeatures && !isEvent && (
                    <div className="mt-4 ph-ignore-input">
                        <Field name="property_type" label="Property Type" data-attr="property-type">
                            {({ value, onChange }) => (
                                <LemonSelect
                                    onChange={(val) => onChange(val)}
                                    value={value as 'DateTime' | 'String' | 'Numeric' | 'Boolean'}
                                    options={[
                                        { value: 'DateTime', label: 'DateTime' },
                                        { value: 'String', label: 'String' },
                                        { value: 'Numeric', label: 'Numeric' },
                                        { value: 'Boolean', label: 'Boolean' },
                                    ]}
                                />
                            )}
                        </Field>
                    </div>
                )}
            </div>
            <LemonDivider />
        </Form>
    )
}
