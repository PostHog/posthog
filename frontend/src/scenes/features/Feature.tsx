import { LemonButton, LemonDivider, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { PageHeader } from 'lib/components/PageHeader'
import { Field, PureField } from 'lib/forms/Field'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'
import { featureLogic } from './featureLogic'
import { Field as KeaField, Form } from 'kea-forms'
import { slugify } from 'lib/utils'
import { FeatureType, NewFeatureType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { urls } from 'scenes/urls'
import { Persons } from 'scenes/persons/Persons'
import { IconFlag, IconPlus } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useState } from 'react'

export const scene: SceneExport = {
    component: Feature,
    logic: featureLogic,
    paramsToProps: ({ params: { id } }): typeof featureLogic['props'] => ({
        id,
    }),
}

function FeatureInstructions({ feature }: { feature: FeatureType | NewFeatureType }): JSX.Element {
    return (
        <CodeSnippet language={Language.JavaScript} wrap>
            {`// Opt a user into the feature
posthog.people.set({
    "$feature_enrollment/${'feature_flag_key' in feature ? feature.feature_flag_key : feature.feature_flag.key}": "${
                feature.stage
            }"
})

// Opt a user out
posthog.people.set({
    "$feature_enrollment/${'feature_flag_key' in feature ? feature.feature_flag_key : feature.feature_flag.key}": false
})
`}
        </CodeSnippet>
    )
}

export function Feature(): JSX.Element {
    const { feature, featureLoading, isFeatureSubmitting, mode } = useValues(featureLogic)
    const { submitFeatureRequest, cancel, setFeatureValue } = useActions(featureLogic)

    const [isModalOpen, setIsModalOpen] = useState(false)

    const toggleModal = (): void => {
        setIsModalOpen(!isModalOpen)
    }

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
                <div className="flex flex-col flex-1 gap-4">
                    {'feature_flag' in feature ? (
                        <PureField label="Connected Feature flag">
                            <LemonButton
                                type="secondary"
                                onClick={() => router.actions.push(urls.featureFlag(feature.feature_flag.id))}
                                icon={<IconFlag />}
                            >
                                {feature.feature_flag.key}
                            </LemonButton>
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
                    <KeaField name="stage" label={<h4 className="font-semibold">Stage</h4>}>
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={(e) => onChange(e.target.value)}
                                options={[
                                    {
                                        label: 'Alpha',
                                        value: 'alpha',
                                    },
                                    {
                                        label: 'Beta',
                                        value: 'beta',
                                    },
                                    {
                                        label: 'General Availability',
                                        value: 'general-availability',
                                    },
                                ]}
                            />
                        )}
                    </KeaField>
                </div>
                {feature.stage !== 'general-availability' && (
                    <div className="w-1/2 max-w-160">
                        <FeatureInstructions feature={feature} />
                    </div>
                )}
            </div>
            <LemonDivider className="my-4" />
            <h3 className="text-xl font-semibold my-4">Persons</h3>
            {'feature_flag' in feature && (
                <Persons
                    fixedProperties={[
                        {
                            key: '$feature_enrollment/' + feature.feature_flag.key,
                            type: PropertyFilterType.Person,
                            operator: PropertyOperator.IsSet,
                        },
                    ]}
                    extraSceneActions={[
                        <LemonButton type="primary" icon={<IconPlus />} onClick={toggleModal}>
                            Add person
                        </LemonButton>
                    ]}
                    extraColumns={[
                        {
                            title: 'Stage',
                            dataIndex: 'properties',
                            render: function Render(_, person: PersonType) {
                                return <span>{person.properties['$feature_enrollment/' + feature.feature_flag.key].toString()}</span>
                            },
                        },
                    ]}
                    compact={true}
                    showExportAction={false}
                />
            )}
            {'feature_flag' in feature && (
                <LemonModal
                    title={"Select person to add"}
                    isOpen={isModalOpen}
                    onClose={toggleModal}
                    width={560}
                >   
                    <Persons 
                        fixedProperties={[
                            {
                                key: '$feature_enrollment/' + feature.feature_flag.key,
                                type: PropertyFilterType.Person,
                                operator: PropertyOperator.IsNotSet,
                            },
                        ]}
                        compact={true} 
                        showFilters={false} 
                        showExportAction={false}
                        extraColumns={[
                            {
                                render: function Render(_, person: PersonType) {
                                    return (
                                        <LemonButton
                                            onClick={() => console.log("HELLO")}
                                            icon={<IconPlus />}
                                            size="small"
                                            type='secondary'
                                        >
                                            Add
                                        </LemonButton>
                                    )
                                },
                            },
                        ]}
                    />
                </LemonModal>
                )
            }
        </Form>
    )
}
