import { LemonButton, LemonDivider, LemonInput, LemonTextArea, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { Field, PureField } from 'lib/forms/Field'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { featureLogic } from './featureLogic'
import { Field as KeaField, Form } from 'kea-forms'
import { Radio } from 'antd'
import { slugify } from 'lib/utils'
import { CodeInstructions } from 'scenes/feature-flags/FeatureFlagInstructions'
import { FeatureType, NewFeatureType } from '~/types'
import { InstructionOption, OPTIONS } from 'scenes/feature-flags/FeatureFlagCodeOptions'
import { LemonFileInput, useUploadFiles } from 'lib/lemon-ui/LemonFileInput/LemonFileInput'
import { useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SQLTable } from '~/queries/Query/SQLTable'
import { urls } from 'scenes/urls'

export const scene: SceneExport = {
    component: Feature,
    logic: featureLogic,
    paramsToProps: ({ params: { id } }): typeof featureLogic['props'] => ({
        id,
    }),
}

function FeatureInstructions({ feature }: { feature: FeatureType | NewFeatureType }): JSX.Element {
    return (
        <CodeInstructions
            headerPrompt="Learn how to gate features"
            featureFlagKey={'feature_flag_key' in feature ? feature.feature_flag_key : feature.feature_flag.key}
            options={[OPTIONS.find((option) => option.value == 'JavaScript') as InstructionOption]}
        />
    )
}

export function Feature(): JSX.Element {
    const { feature, featureLoading, isFeatureSubmitting, mode } = useValues(featureLogic)
    const { submitFeatureRequest, cancel, setFeatureValue, setFeatureManualErrors } = useActions(featureLogic)
    const { objectStorageAvailable } = useValues(preflightLogic)

    const imageDropTargetRef = useRef<HTMLDivElement>(null)

    const { setFilesToUpload, filesToUpload, uploading } = useUploadFiles({
        onUpload: (url) => {
            setFeatureValue('image_url', url)
        },
        onError: (detail) => {
            setFeatureManualErrors({ image_url: `Failed to upload image: ${detail}` })
        },
    })

    return (
        <Form formKey="feature" logic={featureLogic}>
            <PageHeader
                title={
                    !featureLoading ? (
                        <KeaField name="name">
                            {({ value, onChange }) => (
                                <EditableField
                                    name="name"
                                    value={value}
                                    onChange={(value) => {
                                        const shouldUpdateKey =
                                            !('id' in feature) &&
                                            'feature_flag_key' in feature &&
                                            feature.feature_flag_key === slugify(feature.name)
                                        onChange(value)
                                        if (shouldUpdateKey) {
                                            setFeatureValue('feature_flag_key', slugify(value))
                                        }
                                    }}
                                    placeholder="Name this feature"
                                    minLength={1}
                                    maxLength={200} // Sync with the Feature model
                                    mode={mode}
                                    autoFocus={!('id' in feature)}
                                    data-attr="feature-name"
                                />
                            )}
                        </KeaField>
                    ) : (
                        <LemonSkeleton className="w-80 h-10" />
                    )
                }
                buttons={
                    !featureLoading ? (
                        <>
                            <LemonButton
                                type="secondary"
                                onClick={() => cancel()}
                                disabledReason={isFeatureSubmitting ? 'Saving…' : undefined}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                onClick={() => {
                                    submitFeatureRequest(feature)
                                }}
                                loading={isFeatureSubmitting}
                            >
                                Save
                            </LemonButton>
                        </>
                    ) : undefined
                }
                delimited
            />
            <div className="flex gap-4">
                <div className="flex flex-col flex-1 min-w-40 gap-4">
                    {'feature_flag' in feature ? (
                        <PureField label="Feature flag">
                            <Link to={urls.featureFlag(feature.feature_flag.id)} className="font-semibold">
                                {feature.feature_flag.key}
                            </Link>
                        </PureField>
                    ) : (
                        <Field name="feature_flag_key" label="Feature flag key">
                            <LemonInput
                                data-attr="feature-key"
                                className="ph-ignore-input"
                                autoComplete="off"
                                autoCapitalize="off"
                                autoCorrect="off"
                                spellCheck={false}
                                placeholder="Generated from feature name by default"
                            />
                        </Field>
                    )}
                    <Field name="description" label="Description" showOptional>
                        <LemonTextArea
                            className="ph-ignore-input"
                            placeholder="Help your users understand the feature"
                        />
                    </Field>
                    <Field name="documentation_url" label="Documentation URL" showOptional>
                        <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
                    </Field>
                    <Field name="image_url" label="Image URL" showOptional>
                        {({ value, onChange }) => {
                            let isUrlValid = true
                            try {
                                new URL(value)
                            } catch {
                                isUrlValid = false
                            }
                            return (
                                <div className="flex flex-col gap-2" ref={imageDropTargetRef}>
                                    <LemonInput
                                        autoComplete="off"
                                        autoCapitalize="off"
                                        autoCorrect="off"
                                        spellCheck={false}
                                        value={value}
                                        onChange={onChange}
                                    />
                                    {isUrlValid && <img src={value} className="rounded max-w-full" />}
                                    {objectStorageAvailable && (
                                        <LemonFileInput
                                            accept="image/*"
                                            multiple={false}
                                            alternativeDropTargetRef={imageDropTargetRef}
                                            onChange={setFilesToUpload}
                                            loading={uploading}
                                            value={filesToUpload}
                                        />
                                    )}
                                </div>
                            )
                        }}
                    </Field>
                </div>
                {feature.stage !== 'general-availability' && (
                    <div className="w-1/2 max-w-160">
                        <FeatureInstructions feature={feature} />
                    </div>
                )}
            </div>
            <LemonDivider className="my-4" />
            <KeaField name="stage" label={<h3 className="text-xl font-semibold my-4">Stage</h3>}>
                {({ value, onChange }) => (
                    <Radio.Group optionType="default" value={value} onChange={(e) => onChange(e.target.value)}>
                        <Radio value="concept">Concept</Radio>
                        <Radio value="alpha">Alpha</Radio>
                        <Radio value="beta">Beta</Radio>
                        <Radio value="general-availability">General availability</Radio>
                    </Radio.Group>
                )}
            </KeaField>
            {'feature_flag' in feature && feature.stage === 'beta' && (
                <div className="mt-4">
                    <SQLTable
                        query={`SELECT
                    concat(properties.name, ' (', properties.email, ')') AS Person
                FROM persons
                WHERE properties.$feature_enrollment/${feature.feature_flag.key}`}
                    />
                </div>
            )}
        </Form>
    )
}
