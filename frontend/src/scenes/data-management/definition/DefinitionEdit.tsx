import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { VerifiedDefinitionCheckbox } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PageHeader } from 'lib/components/PageHeader'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { getFilterLabel, isCoreFilter } from 'lib/taxonomy'
import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { definitionLogic, DefinitionLogicProps } from 'scenes/data-management/definition/definitionLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'

export const scene: SceneExport = {
    component: DefinitionEdit,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }): DefinitionLogicProps => ({
        id,
    }),
}

export function DefinitionEdit(props: DefinitionLogicProps = {}): JSX.Element {
    const logic = definitionEditLogic(props)
    const { definitionLoading, definitionMissing, hasTaxonomyFeatures, isProperty } = useValues(definitionLogic(props))
    const { editDefinition } = useValues(logic)
    const { saveDefinition } = useActions(logic)
    const { tags, tagsLoading } = useValues(tagsModel)

    const showVerifiedCheckbox =
        hasTaxonomyFeatures && !isCoreFilter(editDefinition.name) && 'verified' in editDefinition

    if (definitionMissing) {
        return <NotFound object="event" />
    }
    return (
        <Form logic={definitionEditLogic} props={props} formKey="editDefinition">
            <PageHeader
                buttons={
                    <>
                        <LemonButton
                            data-attr="cancel-definition"
                            type="secondary"
                            to={
                                !isProperty
                                    ? urls.eventDefinition(editDefinition.id)
                                    : urls.propertyDefinition(editDefinition.id)
                            }
                            disabledReason={definitionLoading ? 'Loading...' : undefined}
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            data-attr="save-definition"
                            type="primary"
                            onClick={() => {
                                saveDefinition({})
                            }}
                            disabledReason={definitionLoading ? 'Loading...' : undefined}
                        >
                            Save
                        </LemonButton>
                    </>
                }
            />

            {definitionLoading ? (
                <div className="space-y-4 mt-4">
                    <LemonSkeleton className="h-10 w-1/3" />
                    <LemonSkeleton className="h-6 w-1/2" />
                    <LemonSkeleton className="h-30 w-1/2" />
                </div>
            ) : (
                <div className="my-4 space-y-4">
                    <div>
                        <h1>Editing "{getFilterLabel(editDefinition.name, TaxonomicFilterGroupType.Events) || ''}"</h1>
                        <div className="flex flex-wrap items-center gap-2 text-muted-alt">
                            <div>Raw event name:</div>
                            <LemonTag className="font-mono">{editDefinition.name}</LemonTag>
                        </div>
                    </div>
                    {hasTaxonomyFeatures && 'tags' in editDefinition && (
                        <div className="ph-ignore-input">
                            <LemonField name="tags" label="Tags" data-attr="definition-tags">
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
                            </LemonField>
                        </div>
                    )}
                    {hasTaxonomyFeatures && (
                        <div className="ph-ignore-input">
                            <LemonField name="description" label="Description" data-attr="definition-description">
                                <LemonTextArea value={editDefinition.description} />
                            </LemonField>
                        </div>
                    )}
                    {showVerifiedCheckbox && (
                        <div className="ph-ignore-input">
                            <LemonField name="verified" label="Verification" data-attr="definition-verified">
                                {({ value, onChange }) => (
                                    <VerifiedDefinitionCheckbox
                                        isProperty={isProperty}
                                        verified={!!value}
                                        onChange={(nextVerified) => {
                                            onChange(nextVerified)
                                        }}
                                    />
                                )}
                            </LemonField>
                        </div>
                    )}

                    {isProperty && (
                        <div className="ph-ignore-input">
                            <LemonField name="property_type" label="Property Type" data-attr="property-type">
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
                            </LemonField>
                        </div>
                    )}
                </div>
            )}
        </Form>
    )
}
