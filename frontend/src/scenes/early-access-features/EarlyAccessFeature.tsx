import { IconX } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, LemonSkeleton, LemonTag, LemonTextArea, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { FlagSelector } from 'lib/components/FlagSelector'
import { NotFound } from 'lib/components/NotFound'
import { PageHeader } from 'lib/components/PageHeader'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { IconFlag, IconHelpOutline } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'
import { personsLogic, PersonsLogicProps } from 'scenes/persons/personsLogic'
import { PersonsSearch } from 'scenes/persons/PersonsSearch'
import { PersonsTable } from 'scenes/persons/PersonsTable'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    EarlyAccessFeatureStage,
    EarlyAccessFeatureTabs,
    EarlyAccessFeatureType,
    FilterType,
    PersonPropertyFilter,
    PropertyFilterType,
    PropertyOperator,
    ReplayTabs,
} from '~/types'

import { earlyAccessFeatureLogic } from './earlyAccessFeatureLogic'
import { InstructionsModal } from './InstructionsModal'

export const scene: SceneExport = {
    component: EarlyAccessFeature,
    logic: earlyAccessFeatureLogic,
    paramsToProps: ({ params: { id } }): (typeof earlyAccessFeatureLogic)['props'] => ({
        id: id && id !== 'new' ? id : 'new',
    }),
}

export function EarlyAccessFeature({ id }: { id?: string } = {}): JSX.Element {
    const {
        earlyAccessFeature,
        earlyAccessFeatureLoading,
        isEarlyAccessFeatureSubmitting,
        isEditingFeature,
        earlyAccessFeatureMissing,
    } = useValues(earlyAccessFeatureLogic)
    const {
        submitEarlyAccessFeatureRequest,
        loadEarlyAccessFeature,
        editFeature,
        updateStage,
        deleteEarlyAccessFeature,
    } = useActions(earlyAccessFeatureLogic)

    const isNewEarlyAccessFeature = id === 'new' || id === undefined

    if (earlyAccessFeatureMissing) {
        return <NotFound object="early access feature" />
    }

    if (earlyAccessFeatureLoading) {
        return <LemonSkeleton active />
    }

    return (
        <Form id="early-access-feature" formKey="earlyAccessFeature" logic={earlyAccessFeatureLogic}>
            <PageHeader
                buttons={
                    !earlyAccessFeatureLoading ? (
                        earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability &&
                        (isNewEarlyAccessFeature || isEditingFeature) ? (
                            <>
                                <LemonButton
                                    type="secondary"
                                    data-attr="cancel-feature"
                                    onClick={() => {
                                        if (isEditingFeature) {
                                            editFeature(false)
                                            loadEarlyAccessFeature()
                                        } else {
                                            router.actions.push(urls.earlyAccessFeatures())
                                        }
                                    }}
                                    disabledReason={isEarlyAccessFeatureSubmitting ? 'Saving…' : undefined}
                                >
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    data-attr="save-feature"
                                    onClick={() => {
                                        submitEarlyAccessFeatureRequest(earlyAccessFeature)
                                    }}
                                    loading={isEarlyAccessFeatureSubmitting}
                                    form="early-access-feature"
                                >
                                    {isNewEarlyAccessFeature ? 'Save as draft' : 'Save'}
                                </LemonButton>
                            </>
                        ) : (
                            <>
                                <LemonButton
                                    data-attr="delete-feature"
                                    status="danger"
                                    type="secondary"
                                    onClick={() => {
                                        LemonDialog.open({
                                            title: 'Permanently delete feature?',
                                            description:
                                                'Doing so will remove any opt in conditions from the feature flag.',
                                            primaryButton: {
                                                children: 'Delete',
                                                type: 'primary',
                                                status: 'danger',
                                                'data-attr': 'confirm-delete-feature',
                                                onClick: () => {
                                                    // conditional above ensures earlyAccessFeature is not NewEarlyAccessFeature
                                                    deleteEarlyAccessFeature(
                                                        (earlyAccessFeature as EarlyAccessFeatureType)?.id
                                                    )
                                                },
                                            },
                                            secondaryButton: {
                                                children: 'Close',
                                                type: 'secondary',
                                            },
                                        })
                                    }}
                                >
                                    Delete
                                </LemonButton>
                                {earlyAccessFeature.stage == EarlyAccessFeatureStage.Beta && (
                                    <LemonButton
                                        data-attr="archive-feature"
                                        type="secondary"
                                        onClick={() => updateStage(EarlyAccessFeatureStage.Archived)}
                                    >
                                        Archive
                                    </LemonButton>
                                )}
                                {earlyAccessFeature.stage == EarlyAccessFeatureStage.Archived && (
                                    <LemonButton
                                        data-attr="reactive-feature"
                                        type="secondary"
                                        onClick={() => updateStage(EarlyAccessFeatureStage.Beta)}
                                    >
                                        Reactivate beta
                                    </LemonButton>
                                )}
                                {earlyAccessFeature.stage == EarlyAccessFeatureStage.Draft && (
                                    <LemonButton
                                        onClick={() => updateStage(EarlyAccessFeatureStage.Beta)}
                                        tooltip="Make beta feature available"
                                        type="primary"
                                    >
                                        Release beta
                                    </LemonButton>
                                )}
                                <LemonDivider vertical />
                                {earlyAccessFeature.stage != EarlyAccessFeatureStage.GeneralAvailability && (
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => editFeature(true)}
                                        loading={false}
                                        data-attr="edit-feature"
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
                    'flex flex-wrap gap-6',
                    isEditingFeature || isNewEarlyAccessFeature ? 'max-w-160' : null
                )}
            >
                <div className="flex flex-col gap-4 flex-2 min-w-[15rem]">
                    {isNewEarlyAccessFeature && (
                        <LemonField name="name" label="Name">
                            <LemonInput data-attr="feature-name" />
                        </LemonField>
                    )}
                    {'feature_flag' in earlyAccessFeature ? (
                        <LemonField.Pure label="Connected Feature flag">
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
                        </LemonField.Pure>
                    ) : (
                        <LemonField
                            name="feature_flag_id"
                            label="Link feature flag (optional)"
                            info={<>A feature flag will be generated from feature name if not provided</>}
                        >
                            {({ value, onChange }) => (
                                <div className="flex">
                                    <FlagSelector value={value} onChange={onChange} />
                                    {value && (
                                        <LemonButton
                                            className="ml-2"
                                            icon={<IconX />}
                                            size="small"
                                            onClick={() => onChange(undefined)}
                                            aria-label="close"
                                        />
                                    )}
                                </div>
                            )}
                        </LemonField>
                    )}
                    {isEditingFeature || isNewEarlyAccessFeature ? (
                        <></>
                    ) : (
                        <div>
                            <b>Stage</b>
                            <div>
                                <LemonTag
                                    type={
                                        earlyAccessFeature.stage === EarlyAccessFeatureStage.Beta
                                            ? 'warning'
                                            : earlyAccessFeature.stage === EarlyAccessFeatureStage.GeneralAvailability
                                            ? 'success'
                                            : 'default'
                                    }
                                    className="mt-2 uppercase"
                                >
                                    {earlyAccessFeature.stage}
                                </LemonTag>
                            </div>
                        </div>
                    )}
                    {isEditingFeature || isNewEarlyAccessFeature ? (
                        <LemonField name="description" label="Description" showOptional>
                            <LemonTextArea
                                className="ph-ignore-input"
                                placeholder="Help your users understand the feature"
                            />
                        </LemonField>
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
                        <LemonField name="documentation_url" label="Documentation URL" showOptional>
                            <LemonInput autoComplete="off" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
                        </LemonField>
                    ) : (
                        <div className="mb-2">
                            <b>Documentation URL</b>
                            <div>
                                {earlyAccessFeature.documentation_url ? (
                                    earlyAccessFeature.documentation_url
                                ) : (
                                    <span className="text-muted">No documentation URL</span>
                                )}
                            </div>
                        </div>
                    )}
                </div>
                {!isEditingFeature && !isNewEarlyAccessFeature && 'id' in earlyAccessFeature && (
                    <div className="flex-3 min-w-[15rem]">
                        <PersonList earlyAccessFeature={earlyAccessFeature} />
                    </div>
                )}
            </div>
        </Form>
    )
}

interface PersonListProps {
    earlyAccessFeature: EarlyAccessFeatureType
}

function featureFlagEnrolmentFilter(earlyAccessFeature: EarlyAccessFeatureType, optedIn: boolean): Partial<FilterType> {
    return {
        events: [
            {
                type: 'events',
                order: 0,
                name: '$feature_enrollment_update',
                properties: [
                    {
                        key: '$feature_enrollment',
                        value: [optedIn ? 'true' : 'false'],
                        operator: 'exact',
                        type: 'event',
                    },
                    {
                        key: '$feature_flag',
                        value: [earlyAccessFeature.feature_flag.key],
                        operator: 'exact',
                        type: 'event',
                    },
                ],
            },
        ],
    }
}

export function PersonList({ earlyAccessFeature }: PersonListProps): JSX.Element {
    const { implementOptInInstructionsModal, activeTab } = useValues(earlyAccessFeatureLogic)
    const { toggleImplementOptInInstructionsModal, setActiveTab } = useActions(earlyAccessFeatureLogic)

    const { featureFlag } = useValues(featureFlagLogic({ id: earlyAccessFeature.feature_flag.id || 'link' }))

    const key = '$feature_enrollment/' + earlyAccessFeature.feature_flag.key

    return (
        <>
            <LemonTabs
                activeKey={activeTab}
                onChange={(newKey) => setActiveTab(newKey)}
                tabs={[
                    {
                        key: EarlyAccessFeatureTabs.OptedIn,
                        label: 'Opted-In Users',
                        content: (
                            <>
                                <PersonsTableByFilter
                                    recordingsFilters={featureFlagEnrolmentFilter(earlyAccessFeature, true)}
                                    properties={[
                                        {
                                            key: key,
                                            type: PropertyFilterType.Person,
                                            operator: PropertyOperator.Exact,
                                            value: ['true'],
                                        },
                                    ]}
                                    emptyState={
                                        <div>
                                            No manual opt-ins. Manually opted-in people will appear here. Start by{' '}
                                            <Link onClick={toggleImplementOptInInstructionsModal}>
                                                implementing public opt-in
                                            </Link>
                                        </div>
                                    }
                                />
                            </>
                        ),
                    },
                    {
                        key: EarlyAccessFeatureTabs.OptedOut,
                        label: 'Opted-Out Users',
                        content: (
                            <PersonsTableByFilter
                                recordingsFilters={featureFlagEnrolmentFilter(earlyAccessFeature, false)}
                                properties={[
                                    {
                                        key: key,
                                        type: PropertyFilterType.Person,
                                        operator: PropertyOperator.Exact,
                                        value: ['false'],
                                    },
                                ]}
                                emptyState={
                                    <div>
                                        No manual opt-outs. Manually opted-out people will appear here. Start by{' '}
                                        <Link onClick={toggleImplementOptInInstructionsModal}>
                                            implementing public opt-out
                                        </Link>
                                    </div>
                                }
                            />
                        ),
                    },
                ]}
            />

            <InstructionsModal
                featureFlag={featureFlag}
                visible={implementOptInInstructionsModal}
                onClose={toggleImplementOptInInstructionsModal}
            />
        </>
    )
}

interface PersonsTableByFilterProps {
    properties: PersonPropertyFilter[]
    emptyState?: JSX.Element
    recordingsFilters: Partial<FilterType>
}

export function PersonsTableByFilter(props: PersonsTableByFilterProps): JSX.Element {
    const personsLogicProps: PersonsLogicProps = {
        cohort: undefined,
        syncWithUrl: false,
        fixedProperties: props.properties,
    }

    return (
        <BindLogic logic={personsLogic} props={personsLogicProps}>
            <PersonsTableByFilterComponent {...props} />
        </BindLogic>
    )
}

interface PersonsTableByFilterComponentProps {
    emptyState?: JSX.Element
    recordingsFilters: Partial<FilterType>
}

function PersonsTableByFilterComponent({
    emptyState,
    recordingsFilters,
}: PersonsTableByFilterComponentProps): JSX.Element {
    const { toggleImplementOptInInstructionsModal } = useActions(earlyAccessFeatureLogic)

    const { persons, personsLoading, listFilters } = useValues(personsLogic)
    const { loadPersons, setListFilters } = useActions(personsLogic)

    return (
        <div className="space-y-2">
            <div className="flex-col">
                <PersonsSearch />
            </div>
            <div className="flex flex-row justify-between">
                <PropertyFilters
                    pageKey="persons-list-page"
                    propertyFilters={listFilters.properties}
                    onChange={(properties) => {
                        setListFilters({ properties })
                        loadPersons()
                    }}
                    endpoint="person"
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.PersonProperties]}
                    showConditionBadge
                />
                <div className="flex flex-row gap-2">
                    <LemonButton
                        key="help-button"
                        onClick={toggleImplementOptInInstructionsModal}
                        sideIcon={<IconHelpOutline />}
                    >
                        Implement public opt-in
                    </LemonButton>
                    <LemonButton
                        key="view-opt-in-session-recordings"
                        onClick={() => {
                            router.actions.push(urls.replay(ReplayTabs.Recent, recordingsFilters))
                        }}
                        type="secondary"
                        disabledReason={
                            personsLoading ? 'Loading…' : persons.results.length === 0 ? 'No users to view' : undefined
                        }
                    >
                        View recordings
                    </LemonButton>
                </div>
            </div>
            <PersonsTable
                people={persons.results}
                loading={personsLoading}
                hasPrevious={!!persons.previous}
                hasNext={!!persons.next}
                loadPrevious={() => loadPersons(persons.previous)}
                loadNext={() => loadPersons(persons.next)}
                compact={true}
                extraColumns={[]}
                emptyState={emptyState}
            />
        </div>
    )
}
