import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { createRef } from 'react'

import { IconImage } from '@posthog/icons'
import { LemonSkeleton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { PropertyStatusControl } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { ImageCarousel } from 'lib/components/ImageCarousel/ImageCarousel'
import { NotFound } from 'lib/components/NotFound'
import { ObjectTags } from 'lib/components/ObjectTags/ObjectTags'
import { FEATURE_FLAGS } from 'lib/constants'
import { useUploadFiles } from 'lib/hooks/useUploadFiles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonFileInput } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { definitionEditLogic } from 'scenes/data-management/definition/definitionEditLogic'
import { DefinitionLogicProps, definitionLogic } from 'scenes/data-management/definition/definitionLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { tagsModel } from '~/models/tagsModel'
import { isCoreFilter } from '~/taxonomy/helpers'
import { ObjectMediaPreview } from '~/types'

import { getEventDefinitionIcon, getPropertyDefinitionIcon } from '../events/DefinitionHeader'

export const scene: SceneExport<DefinitionLogicProps> = {
    component: DefinitionEdit,
    logic: definitionLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function DefinitionEdit(props: DefinitionLogicProps): JSX.Element {
    const logic = definitionEditLogic(props)
    const definitionLogicInstance = definitionLogic(props)
    const { definitionLoading, definitionMissing, isProperty } = useValues(definitionLogicInstance)
    const { editDefinition } = useValues(logic)
    const { saveDefinition } = useActions(logic)
    const { tags, tagsLoading } = useValues(tagsModel)
    const { objectStorageAvailable } = useValues(preflightLogic)

    const allowVerification = !isCoreFilter(editDefinition.name) && 'verified' in editDefinition

    const showHiddenOption = 'hidden' in editDefinition

    const { previews, previewsLoading } = useValues(definitionLogicInstance)
    const { createMediaPreview, deleteMediaPreview } = useActions(definitionLogicInstance)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (_url, _fileName, uploadedMediaId) => {
            createMediaPreview(uploadedMediaId)
        },
        onError: (detail) => {
            lemonToast.error(`Error uploading image: ${detail}`)
        },
    })

    const mediaPreviewDragTarget = createRef<HTMLDivElement>()

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
                            <LemonField name="description" label="Description" data-attr="definition-description">
                                <LemonTextArea value={editDefinition.description} />
                            </LemonField>
                        </div>

                        <FlaggedFeature flag={FEATURE_FLAGS.EVENT_MEDIA_PREVIEWS}>
                            {objectStorageAvailable && (
                                <div className="ph-ignore-input">
                                    <LemonField
                                        name="media_preview"
                                        label={
                                            <LemonLabel info="Previews show where a client side event is triggered. Upload a screenshot or design.">
                                                Media preview
                                            </LemonLabel>
                                        }
                                    >
                                        <div>
                                            {previewsLoading && (
                                                <div className="flex items-center gap-2">
                                                    <Spinner />
                                                    <span className="text-secondary">Loading preview...</span>
                                                </div>
                                            )}

                                            <div className="mb-4">
                                                <div
                                                    ref={mediaPreviewDragTarget}
                                                    className="border-2 border-dashed rounded p-4 flex items-center justify-center cursor-pointer"
                                                    onClick={(e) => {
                                                        if (e.target === e.currentTarget) {
                                                            const input = mediaPreviewDragTarget.current?.querySelector(
                                                                'input[type="file"]'
                                                            ) as HTMLInputElement
                                                            input?.click()
                                                        }
                                                    }}
                                                >
                                                    <LemonFileInput
                                                        accept="image/*"
                                                        multiple={false}
                                                        onChange={setFilesToUpload}
                                                        loading={uploading}
                                                        value={filesToUpload}
                                                        alternativeDropTargetRef={mediaPreviewDragTarget}
                                                        callToAction={
                                                            <div className="flex items-center gap-2">
                                                                <IconImage />
                                                                <span>Click or drag and drop to upload an image</span>
                                                            </div>
                                                        }
                                                    />
                                                </div>
                                            </div>

                                            {previews && previews.length > 0 && (
                                                <ImageCarousel
                                                    imageUrls={previews.map((p: ObjectMediaPreview) => p.media_url)}
                                                    onDelete={(url: string) => {
                                                        const preview = previews.find(
                                                            (p: ObjectMediaPreview) => p.media_url === url
                                                        )
                                                        if (preview) {
                                                            deleteMediaPreview(preview.id)
                                                        }
                                                    }}
                                                />
                                            )}
                                        </div>
                                    </LemonField>
                                </div>
                            )}
                        </FlaggedFeature>

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
