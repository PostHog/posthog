import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { PropertyStatusControl } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { DefinitionLogicProps, definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { isCoreFilter } from '~/taxonomy/helpers'
import { AvailableFeature } from '~/types'

import { getEventDefinitionIcon, getPropertyDefinitionIcon } from '../events/DefinitionHeader'

export const scene: SceneExport<DefinitionLogicProps> = {
    component: DefinitionEdit,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function DefinitionEdit(props: DefinitionLogicProps): JSX.Element {
    const logic = definitionEditLogic(props)
    const { definitionLoading, definitionMissing, hasTaxonomyFeatures, isProperty } = useValues(definitionLogic(props))
    const { editDefinition } = useValues(logic)
    const { saveDefinition } = useActions(logic)
    const { tags, tagsLoading } = useValues(tagsModel)

    const allowVerification = hasTaxonomyFeatures && !isCoreFilter(editDefinition.name) && 'verified' in editDefinition

    const showHiddenOption = hasTaxonomyFeatures && 'hidden' in editDefinition

    if (definitionMissing) {
        return <NotFound object="event" />
    }
    return (
        <Form logic={definitionEditLogic} props={props} formKey="editDefinition">
            <SceneContent>
                <SceneTitleSection
                    name={editDefinition.name}
                    resourceType={{
                        type: isProperty ? 'property definition' : 'event definition',
                        forceIcon: isProperty
                            ? getPropertyDefinitionIcon(editDefinition)
                            : getEventDefinitionIcon(editDefinition),
                    }}
                    forceBackTo={
                        isProperty
                            ? {
                                  path: urls.propertyDefinitions(),
                                  name: 'Property definitions',
                                  key: 'properties',
                              }
                            : {
                                  path: urls.eventDefinitions(),
                                  name: 'Event definitions',
                                  key: 'events',
                              }
                    }
                    actions={
                        <>
                            <LemonButton
                                data-attr="save-definition"
                                type="primary"
                                size="small"
                                onClick={() => {
                                    saveDefinition({})
                                }}
                                disabledReason={definitionLoading ? 'Loading...' : undefined}
                            >
                                Save
                            </LemonButton>
                            <LemonButton
                                data-attr="cancel-definition"
                                type="secondary"
                                size="small"
                                to={
                                    !isProperty
                                        ? urls.eventDefinition(editDefinition.id)
                                        : urls.propertyDefinition(editDefinition.id)
                                }
                                disabledReason={definitionLoading ? 'Loading...' : undefined}
                            >
                                Cancel
                            </LemonButton>
                        </>
                    }
                />

                {definitionLoading ? (
                    <div className="deprecated-space-y-4">
                        <LemonSkeleton className="h-10 w-1/3" />
                        <LemonSkeleton className="h-6 w-1/2" />
                        <LemonSkeleton className="h-30 w-1/2" />
                    </div>
                ) : (
                    <div className="deprecated-space-y-4">
                        <div className="flex flex-wrap items-center gap-2 text-secondary">
                            <div>{isProperty ? 'Property' : 'Event'} name:</div>
                            <LemonTag className="font-mono">{editDefinition.name}</LemonTag>
                        </div>
                        {hasTaxonomyFeatures ? (
                            <>
                                {'tags' in editDefinition && (
                                    <div className="ph-ignore-input">
                                        <LemonField name="tags" label="Tags" data-attr="definition-tags">
                                            {({ value, onChange }) => (
                                                <ObjectTags
                                                    className="definition-tags"
                                                    saving={definitionLoading || tagsLoading}
                                                    tags={value || []}
                                                    onChange={(tags) => onChange(tags)}
                                                    style={{ marginBottom: 4 }}
                                                    tagsAvailable={tags}
                                                />
                                            )}
                                        </LemonField>
                                    </div>
                                )}

                                <div className="ph-ignore-input">
                                    <LemonField
                                        name="description"
                                        label="Description"
                                        data-attr="definition-description"
                                    >
                                        <LemonTextArea value={editDefinition.description} />
                                    </LemonField>
                                </div>

                                {(allowVerification || showHiddenOption) && (
                                    <div className="ph-ignore-input">
                                        <LemonField name="verified" label="Status" data-attr="definition-status">
                                            {({ value: verified, onChange }) => (
                                                <LemonField name="hidden">
                                                    {({ value: hidden, onChange: onHiddenChange }) => (
                                                        <PropertyStatusControl
                                                            isProperty={isProperty}
                                                            verified={!!verified}
                                                            hidden={!!hidden}
                                                            showHiddenOption={showHiddenOption}
                                                            allowVerification={allowVerification}
                                                            onChange={({
                                                                verified: newVerified,
                                                                hidden: newHidden,
                                                            }) => {
                                                                onChange(newVerified)
                                                                onHiddenChange(newHidden)
                                                            }}
                                                        />
                                                    )}
                                                </LemonField>
                                            )}
                                        </LemonField>
                                    </div>
                                )}
                            </>
                        ) : (
                            <PayGateMini feature={AvailableFeature.INGESTION_TAXONOMY} />
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
            </SceneContent>
        </Form>
    )
}
