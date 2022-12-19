import { PageHeader } from 'lib/components/PageHeader'
import { DefinitionPageMode } from 'scenes/data-management/definition/definitionLogic'
import { useActions, useValues } from 'kea'
import { definitionEditLogic, DefinitionEditLogicProps } from 'scenes/data-management/definition/definitionEditLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Col, Divider, Row } from 'antd'
import { Field } from 'lib/forms/Field'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { getPropertyLabel, isPostHogProp } from 'lib/components/PropertyKeyInfo'
import { VerifiedEventCheckbox } from 'lib/components/DefinitionPopup/DefinitionPopupContents'
import { LemonSelect } from 'lib/components/LemonSelect'
import { Form } from 'kea-forms'
import { tagsModel } from '~/models/tagsModel'

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
            <Divider />
            <Row gutter={[16, 24]} style={{ maxWidth: 640 }} className="ph-ignore-input">
                <Col span={24}>
                    <h1>{getPropertyLabel(definition.name) || ''}</h1>
                    <div className="definition-sent-as">
                        Raw event name: <pre>{definition.name}</pre>
                    </div>
                </Col>
            </Row>
            {hasTaxonomyFeatures && (
                <Row gutter={[16, 24]} className="mt-4 ph-ignore-input" style={{ maxWidth: 640 }}>
                    <Col span={24}>
                        <Field name="description" label="Description" data-attr="definition-description">
                            <LemonTextArea value={definition.description} />
                        </Field>
                    </Col>
                </Row>
            )}
            {hasTaxonomyFeatures && isEvent && !isPostHogProp(definition.name) && 'verified' in definition && (
                <Row gutter={[16, 24]} className="mt-4 ph-ignore-input" style={{ maxWidth: 640 }}>
                    <Col span={24}>
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
                    </Col>
                </Row>
            )}
            {hasTaxonomyFeatures && 'tags' in definition && (
                <Row gutter={[16, 24]} className="mt-4 ph-ignore-input" style={{ maxWidth: 640 }}>
                    <Col span={24}>
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
                    </Col>
                </Row>
            )}
            {hasTaxonomyFeatures && !isEvent && (
                <Row gutter={[16, 24]} className="mt-4 ph-ignore-input" style={{ maxWidth: 640 }}>
                    <Col span={24}>
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
                    </Col>
                </Row>
            )}
            <Divider />
        </Form>
    )
}
