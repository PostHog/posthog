import { LemonButton, LemonInput, LemonSelect, LemonTag, LemonTextArea } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { Field, PureField } from 'lib/forms/Field'
import { SceneExport } from 'scenes/sceneTypes'
import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'
import { Field as KeaField, Form } from 'kea-forms'
import { FeatureType, PersonType, PropertyFilterType, PropertyOperator } from '~/types'
import { urls } from 'scenes/urls'
import { PersonsScene } from 'scenes/persons/Persons'
import { IconDelete, IconFlag, IconHelpOutline } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { useState } from 'react'
import { Popover } from 'lib/lemon-ui/Popover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { PersonLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import api from 'lib/api'
import clsx from 'clsx'
import { InstructionsModal } from './InstructionsModal'

export const scene: SceneExport = {
    component: EarlyAccessFeature,
    logic: earlyAccessFeatureLogic,
    paramsToProps: ({ params: { id } }): (typeof earlyAccessFeatureLogic)['props'] => ({
        id,
    }),
}

export function EarlyAccessFeature(): JSX.Element {
    const { feature, featureLoading, isFeatureSubmitting, isEditingFeature } = useValues(earlyAccessFeatureLogic)
    const { submitFeatureRequest, cancel, editFeature } = useActions(earlyAccessFeatureLogic)

    return (
        <Form formKey="feature" logic={earlyAccessFeatureLogic}>
            <PageHeader
                title={isEditingFeature && !('id' in feature) ? 'New Feature Release' : feature.name}
                buttons={
                    !featureLoading ? (
                        isEditingFeature ? (
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
                        ) : (
                            <LemonButton
                                type="secondary"
                                htmlType="submit"
                                onClick={() => {
                                    editFeature(true)
                                }}
                                loading={false}
                            >
                                Edit
                            </LemonButton>
                        )
                    ) : undefined
                }
                delimited
            />
            <div className={clsx('flex', 'flex-row', 'gap-6', isEditingFeature ? 'max-w-160' : null)}>
                <div className="flex flex-col gap-4" style={{ flex: 2 }}>
                    {isEditingFeature && !('id' in feature) && (
                        <Field name="name" label="Name">
                            <LemonInput data-attr="feature-name" />
                        </Field>
                    )}
                    {'feature_flag' in feature ? (
                        <PureField label="Connected Feature flag">
                            <div>
                                <LemonButton
                                    type="secondary"
                                    onClick={() =>
                                        feature.feature_flag &&
                                        router.actions.push(urls.featureFlag(feature.feature_flag.id))
                                    }
                                    icon={<IconFlag />}
                                >
                                    {feature.feature_flag.key}
                                </LemonButton>
                            </div>
                        </PureField>
                    ) : (
                        <Field
                            name="feature_flag_id"
                            label="Link feature flag (optional)"
                            info={<>A feature flag will be generated from feature name by default</>}
                        >
                            {({ value, onChange }) => (
                                <div>
                                    <FlagSelector value={value} onChange={onChange} />
                                </div>
                            )}
                        </Field>
                    )}
                    {isEditingFeature ? (
                        <KeaField name="stage" label={<h4 className="font-semibold">Stage</h4>}>
                            {({ value, onChange }) => (
                                <div>
                                    <LemonSelect
                                        value={value}
                                        onChange={onChange}
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
                                </div>
                            )}
                        </KeaField>
                    ) : (
                        <div className="mb-2">
                            <b>Stage</b>
                            <div>
                                <LemonTag type="highlight" className="mt-2 uppercase">
                                    {feature.stage}
                                </LemonTag>
                            </div>
                        </div>
                    )}
                    {isEditingFeature ? (
                        <Field name="description" label="Description" showOptional>
                            <LemonTextArea
                                className="ph-ignore-input"
                                placeholder="Help your users understand the feature"
                            />
                        </Field>
                    ) : (
                        <div className="mb-2">
                            <b>Description</b>
                            <div>
                                {feature.description ? (
                                    feature.description
                                ) : (
                                    <span className="text-muted">No description</span>
                                )}
                            </div>
                        </div>
                    )}
                    {isEditingFeature ? (
                        <Field name="documentation_url" label="Documentation URL" showOptional>
                            <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
                        </Field>
                    ) : (
                        <div className="mb-2">
                            <b>Documentation Url</b>
                            <div>
                                {feature.documentation_url ? (
                                    feature.documentation_url
                                ) : (
                                    <span className="text-muted">No documentation url</span>
                                )}
                            </div>
                        </div>
                    )}
                </div>
                {!isEditingFeature && 'id' in feature && (
                    <div style={{ flex: 3 }}>
                        <PersonList feature={feature} />
                    </div>
                )}
            </div>
        </Form>
    )
}

interface FlagSelectorProps {
    value: number | undefined
    onChange: (value: any) => void
}

function FlagSelector({ value, onChange }: FlagSelectorProps): JSX.Element {
    const [visible, setVisible] = useState(false)

    const { featureFlag } = useValues(featureFlagLogic({ id: value || 'link' }))

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        groupType: TaxonomicFilterGroupType.FeatureFlags,
        value,
        onChange: (_, __, item) => {
            'id' in item && item.id && onChange(item.id)
            setVisible(false)
        },
        taxonomicGroupTypes: [TaxonomicFilterGroupType.FeatureFlags],
        optionsFromProp: undefined,
        popoverEnabled: true,
        selectFirstItem: true,
        taxonomicFilterLogicKey: 'universalSearch',
    }

    return (
        <Popover
            overlay={<TaxonomicFilter {...taxonomicFilterLogicProps} />}
            visible={visible}
            placement="right-start"
            fallbackPlacements={['bottom']}
            onClickOutside={() => setVisible(false)}
        >
            <LemonButton type="secondary" onClick={() => setVisible(!visible)}>
                {!!featureFlag.key ? featureFlag.key : 'Select flag'}
            </LemonButton>
        </Popover>
    )
}

interface PersonListProps {
    feature: FeatureType
}

function PersonList({ feature }: PersonListProps): JSX.Element {
    const { implementOptInInstructionsModal } = useValues(earlyAccessFeatureLogic)
    const { toggleImplementOptInInstructionsModal } = useActions(earlyAccessFeatureLogic)

    const key = '$feature_enrollment/' + feature.feature_flag.key
    const personLogicProps: PersonLogicProps = {
        cohort: undefined,
        syncWithUrl: false,
        fixedProperties: [
            {
                key: key,
                type: PropertyFilterType.Person,
                operator: PropertyOperator.Exact,
                value: ['true'],
            },
        ],
    }
    const logic = personsLogic(personLogicProps)
    const { persons } = useValues(logic)

    const { featureFlag } = useValues(featureFlagLogic({ id: feature.feature_flag.id || 'link' }))

    const optUserOut = async (person: PersonType): Promise<void> => {
        await api.persons.updateProperty(person.id as string, key, false)
        logic.actions.setPerson({ ...person, properties: { ...person.properties, [key]: false } })
    }

    return (
        <BindLogic logic={personsLogic} props={personLogicProps}>
            <h3 className="text-xl font-semibold">Opted-In Users</h3>
            <PersonsScene
                showSearch={persons.results.length > 0}
                showFilters={persons.results.length > 0}
                extraColumns={[
                    {
                        render: function Render(_, person: PersonType) {
                            return (
                                person.properties['$feature_enrollment/' + feature.feature_flag.key] && (
                                    <LemonButton
                                        onClick={() => optUserOut(person)}
                                        icon={<IconDelete />}
                                        status="danger"
                                        size="small"
                                    />
                                )
                            )
                        },
                    },
                ]}
                extraSceneActions={
                    persons.results.length > 0
                        ? [
                              <LemonButton
                                  key="help-button"
                                  onClick={toggleImplementOptInInstructionsModal}
                                  sideIcon={<IconHelpOutline />}
                              >
                                  Implement public opt-in
                              </LemonButton>,
                          ]
                        : []
                }
                compact={true}
                showExportAction={false}
                emptyState={
                    <div>
                        No manual opt-ins. Manually opted-in people will appear here. Start by{' '}
                        <a onClick={toggleImplementOptInInstructionsModal}>implementing public opt-in</a>
                    </div>
                }
            />
            <InstructionsModal
                featureFlag={featureFlag}
                visible={implementOptInInstructionsModal}
                onClose={toggleImplementOptInInstructionsModal}
            />
        </BindLogic>
    )
}
