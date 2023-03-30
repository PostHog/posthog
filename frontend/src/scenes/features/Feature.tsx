import { LemonButton, LemonInput, LemonTextArea } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { Field } from 'lib/forms/Field'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { featureLogic } from './featureLogic'
import { Field as KeaField, Form } from 'kea-forms'
import { Radio } from 'antd'
import { slugify } from 'lib/utils'

export const scene: SceneExport = {
    component: Feature,
    logic: featureLogic,
    paramsToProps: ({ params: { id } }): typeof featureLogic['props'] => ({
        id,
    }),
}

export function Feature(): JSX.Element {
    const { feature, featureLoading, isFeatureSubmitting, mode } = useValues(featureLogic)
    const { submitFeatureRequest, cancel, setFeatureValue } = useActions(featureLogic)

    return (
        <Form formKey="feature" logic={featureLogic} className="space-y-4">
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

            <Field name="feature_flag_key" label="Flag key">
                <LemonInput
                    data-attr="feature-key"
                    className="ph-ignore-input"
                    autoComplete="off"
                    autoCapitalize="off"
                    autoCorrect="off"
                    spellCheck={false}
                    placeholder="Reserve a feature flag key"
                />
            </Field>
            <Field name="description" label="Description">
                <LemonTextArea className="ph-ignore-input" placeholder="Help your users understand the feature" />
            </Field>
            <Field name="image_url" label="Image URL" showOptional>
                <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
            </Field>

            <Field name="documentation_url" label="Documentation URL" showOptional>
                <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
            </Field>
            <Field name="stage" label="Stage">
                {({ value, onChange }) => (
                    <Radio.Group optionType="default" value={value} onChange={(e) => onChange(e.target.value)}>
                        <Radio value="concept">Concept</Radio>
                        {/* TODO: <Radio value="alpha">Alpha</Radio> */}
                        <Radio value="beta">Beta</Radio>
                        <Radio value="general-availability">General availability</Radio>
                    </Radio.Group>
                )}
            </Field>
        </Form>
    )
}
