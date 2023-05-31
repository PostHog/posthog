import { LemonButton, LemonInput, LemonTag, LemonTextArea } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PageHeader } from 'lib/components/PageHeader'
import { Field, PureField } from 'lib/forms/Field'
import { SceneExport } from 'scenes/sceneTypes'
import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'
import { Form } from 'kea-forms'
import { EarlyAccessFeatureStage, EarlyAccessFeatureType, PropertyFilterType, PropertyOperator } from '~/types'
import { urls } from 'scenes/urls'
import { PersonsScene } from 'scenes/persons/Persons'
import { IconClose, IconFlag, IconHelpOutline } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { useState } from 'react'
import { Popover } from 'lib/lemon-ui/Popover'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterLogicProps } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { PersonsLogicProps, personsLogic } from 'scenes/persons/personsLogic'
import clsx from 'clsx'
import { InstructionsModal } from './InstructionsModal'
import { Col, Popconfirm, Row } from 'antd'

export const scene: SceneExport = {
    component: EarlyAccessFeature,
    logic: earlyAccessFeatureLogic,
    paramsToProps: ({ params: { id } }): (typeof earlyAccessFeatureLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
}

export function EarlyAccessFeature({ id }: { id?: string } = {}): JSX.Element {
    const { earlyAccessFeature, earlyAccessFeatureLoading, isEarlyAccessFeatureSubmitting, isEditingFeature } =
        useValues(earlyAccessFeatureLogic)
    const { submitEarlyAccessFeatureRequest, cancel, editFeature, promote, deleteEarlyAccessFeature } =
        useActions(earlyAccessFeatureLogic)

    const isNewEarlyAccessFeature = id === 'new' || id === undefined

    return (
        <Form formKey="earlyAccessFeature" logic={earlyAccessFeatureLogic}>
            <PageHeader
                title={isNewEarlyAccessFeature ? 'New Feature Release' : earlyAccessFeature.name}
                buttons={
                    !earlyAccessFeatureLoading ? (
                        earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability &&
                        (isNewEarlyAccessFeature || isEditingFeature) ? (
                            <>
                                <LemonButton
                                    type="secondary"
                                    onClick={() => cancel()}
                                    disabledReason={isEarlyAccessFeatureSubmitting ? 'Saving…' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    onClick={() => {
                                        submitEarlyAccessFeatureRequest(earlyAccessFeature)
                                    }}
                                    loading={isEarlyAccessFeatureSubmitting}
                                >
                                    Save
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <Popconfirm
                                    title={
                                        <>
                                            Permanently delete feature? <br />
                                            <b>Doing so will remove any opt in conditions from the feature flag.</b>
                                        </>
                                    }
                                    okText="Delete"
                                    okType="danger"
                                    placement="topLeft"
                                    onConfirm={() => {
                                        // conditional above ensures earlyAccessFeature is not NewEarlyAccessFeature
                                        deleteEarlyAccessFeature((earlyAccessFeature as EarlyAccessFeatureType)?.id)
                                    }}
                                >
                                    <LemonButton data-attr="delete-feature" status="danger" type="secondary">
                                        Delete
                                    </LemonButton>
                                </Popconfirm>

                                {earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability && (
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
                                )}
                            </>
                        )
                    ) : undefined
                }
                delimited
            />
            <div
                className={clsx(
                    'flex',
                    'flex-row',
                    'gap-6',
                    isEditingFeature || isNewEarlyAccessFeature ? 'max-w-160' : null
                )}
            >
                <div className="flex flex-col gap-4" style={{ flex: 2 }}>
                    {isNewEarlyAccessFeature && (
                        <Field name="name" label="Name">
                            <LemonInput data-attr="feature-name" />
                        </Field>
                    )}
                    {'feature_flag' in earlyAccessFeature ? (
                        <PureField label="Connected Feature flag">
                            <div>
                                <LemonButton
                                    type="secondary"
                                    onClick={() =>
                                        earlyAccessFeature.feature_flag &&
                                        router.actions.push(urls.featureFlag(earlyAccessFeature.feature_flag.id))
                                    }
                                    icon={<IconFlag />}
                                >
                                    {earlyAccessFeature.feature_flag.key}
                                </LemonButton>
                            </div>
                        </PureField>
                    ) : (
                        <Field
                            name="feature_flag_id"
                            label="Link feature flag (optional)"
                            info={<>A feature flag will be generated from feature name if not provided</>}
                        >
                            {({ value, onChange }) => (
                                <Row>
                                    <FlagSelector value={value} onChange={onChange} />
                                    {value && (
                                        <LemonButton
                                            className="ml-2"
                                            icon={<IconClose />}
                                            size="small"
                                            status="stealth"
                                            onClick={() => onChange(undefined)}
                                            aria-label="close"
                                        />
                                    )}
                                </Row>
                            )}
                        </Field>
                    )}
                    {isEditingFeature || isNewEarlyAccessFeature ? (
                        <></>
                    ) : (
                        <div className="mb-2 flex flex-row justify-between">
                            <Col>
                                <b>Stage</b>
                                <div>
                                    <LemonTag type="highlight" className="mt-2 uppercase">
                                        {earlyAccessFeature.stage}
                                    </LemonTag>
                                </div>
                            </Col>
                            {earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability && (
                                <LemonButton
                                    onClick={() => promote()}
                                    tooltip={'Make feature generally available'}
                                    type="secondary"
                                >
                                    Promote
                                </LemonButton>
                            )}
                        </div>
                    )}
                    {isEditingFeature || isNewEarlyAccessFeature ? (
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
                                {earlyAccessFeature.description ? (
                                    earlyAccessFeature.description
                                ) : (
                                    <span className="text-muted">No description</span>
                                )}
                            </div>
                        </div>
                    )}
                    {isEditingFeature || isNewEarlyAccessFeature ? (
                        <Field name="documentation_url" label="Documentation URL" showOptional>
                            <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
                        </Field>
                    ) : (
                        <div className="mb-2">
                            <b>Documentation Url</b>
                            <div>
                                {earlyAccessFeature.documentation_url ? (
                                    earlyAccessFeature.documentation_url
                                ) : (
                                    <span className="text-muted">No documentation url</span>
                                )}
                            </div>
                        </div>
                    )}
                </div>
                {!isEditingFeature && !isNewEarlyAccessFeature && 'id' in earlyAccessFeature && (
                    <div style={{ flex: 3 }}>
                        <PersonList earlyAccessFeature={earlyAccessFeature} />
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

export function FlagSelector({ value, onChange }: FlagSelectorProps): JSX.Element {
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
        taxonomicFilterLogicKey: 'flag-selectorz',
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
    earlyAccessFeature: EarlyAccessFeatureType
}

function PersonList({ earlyAccessFeature }: PersonListProps): JSX.Element {
    const { implementOptInInstructionsModal } = useValues(earlyAccessFeatureLogic)
    const { toggleImplementOptInInstructionsModal } = useActions(earlyAccessFeatureLogic)

    const key = '$feature_enrollment/' + earlyAccessFeature.feature_flag.key
    const personsLogicProps: PersonsLogicProps = {
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
    const logic = personsLogic(personsLogicProps)
    const { persons } = useValues(logic)
    const { featureFlag } = useValues(featureFlagLogic({ id: earlyAccessFeature.feature_flag.id || 'link' }))

    return (
        <BindLogic logic={personsLogic} props={personsLogicProps}>
            <h3 className="text-xl font-semibold">Opted-In Users</h3>
            <PersonsScene
                showSearch={persons.results.length > 0}
                showFilters={persons.results.length > 0}
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
