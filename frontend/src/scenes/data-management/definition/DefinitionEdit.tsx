import React from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { DefinitionPageMode } from 'scenes/data-management/definition/definitionLogic'
import { useActions, useValues } from 'kea'
import { definitionEditLogic, DefinitionEditLogicProps } from 'scenes/data-management/definition/definitionEditLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { Col, Divider, Row } from 'antd'
import { VerticalForm } from 'lib/forms/VerticalForm'
import { Field } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { LemonTextArea } from 'lib/components/LemonTextArea/LemonTextArea'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'

export function DefinitionEdit(props: DefinitionEditLogicProps): JSX.Element {
    const logic = definitionEditLogic(props)
    const { definitionLoading, definition, hasTaxonomyFeatures } = useValues(logic)
    const { setPageMode, saveDefinition } = useActions(logic)

    const buttons = (
        <>
            <LemonButton
                data-attr="cancel-definition"
                type="secondary"
                onClick={() => {
                    setPageMode(DefinitionPageMode.View)
                }}
                style={{ marginRight: 8 }}
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
                style={{ marginRight: 8 }}
                disabled={definitionLoading}
            >
                Save
            </LemonButton>
        </>
    )

    return (
        <VerticalForm logic={definitionEditLogic} props={props} formKey="definition">
            <PageHeader title="Edit event" buttons={buttons} />
            <Divider />
            <Row gutter={[16, 24]} style={{ maxWidth: 640 }} className="ph-ignore-input">
                <Col span={24}>
                    <Field name="name" label="Name" className="definition-name">
                        <LemonInput data-attr="definition-name" value={definition.name} />
                    </Field>
                    <div className="definition-sent-as">
                        Raw event name: <pre>{definition.name}</pre>
                    </div>
                </Col>
            </Row>
            {hasTaxonomyFeatures && (
                <Row gutter={[16, 24]} className="mt ph-ignore-input" style={{ maxWidth: 640 }}>
                    <Col span={24}>
                        <Field name="description" label="Description" data-attr="definition-description">
                            <LemonTextArea value={definition.description} />
                        </Field>
                    </Col>
                </Row>
            )}
            {hasTaxonomyFeatures && 'tags' in definition && (
                <Row gutter={[16, 24]} className="mt ph-ignore-input" style={{ maxWidth: 640 }}>
                    <Col span={24}>
                        <Field name="tags" label="Tags" data-attr="definition-tags">
                            {({ value, onChange }) => (
                                <ObjectTags
                                    className="definition-tags"
                                    tags={value || []}
                                    onChange={(_, tags) => onChange(tags)}
                                    style={{ marginBottom: 4 }}
                                />
                            )}
                        </Field>
                    </Col>
                </Row>
            )}
            <Divider />
            <div className="definition-footer-buttons">{buttons}</div>
        </VerticalForm>
    )
}
