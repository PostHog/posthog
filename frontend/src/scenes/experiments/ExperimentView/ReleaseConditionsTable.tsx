import { useActions, useValues } from 'kea'

import { IconFlag } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonModal, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'

import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { FeatureFlagLogicProps, featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { groupsModel } from '~/models/groupsModel'
import { FeatureFlagGroupType } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { modalsLogic } from '../modalsLogic'

export function ReleaseConditionsModal(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { setExperiment } = useActions(experimentLogic)
    const { closeReleaseConditionsModal } = useActions(modalsLogic)
    const { isReleaseConditionsModalOpen } = useValues(modalsLogic)

    const _featureFlagLogic = featureFlagLogic({ id: experiment.feature_flag?.id ?? null } as FeatureFlagLogicProps)
    const { featureFlag, nonEmptyVariants } = useValues(_featureFlagLogic)
    const { setFeatureFlagFilters, saveSidebarExperimentFeatureFlag } = useActions(_featureFlagLogic)

    return (
        <LemonModal
            isOpen={isReleaseConditionsModalOpen}
            onClose={closeReleaseConditionsModal}
            width={600}
            title="Change release conditions"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeReleaseConditionsModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={async () => {
                            await saveSidebarExperimentFeatureFlag(featureFlag)

                            const currentFlag = experiment.feature_flag
                            if (currentFlag && featureFlag) {
                                setExperiment({
                                    feature_flag: {
                                        ...currentFlag,
                                        ...featureFlag,
                                        id: currentFlag.id, // keep existing non-null id
                                        team_id: currentFlag.team_id,
                                    },
                                })
                            }

                            closeReleaseConditionsModal()
                        }}
                        type="primary"
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="deprecated-space-y-4">
                <LemonBanner type="info">
                    Adjusting user targeting may impact the validity of your results. Adjust only if you're aware of how
                    changes will affect your experiment.
                </LemonBanner>

                <FeatureFlagReleaseConditions
                    id={`${experiment.feature_flag?.id}`}
                    filters={featureFlag?.filters ?? []}
                    onChange={setFeatureFlagFilters}
                    nonEmptyFeatureFlagVariants={nonEmptyVariants}
                />
            </div>
        </LemonModal>
    )
}

export function ReleaseConditionsTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed } = useActions(experimentLogic)
    const { openReleaseConditionsModal } = useActions(modalsLogic)
    const { aggregationLabel } = useValues(groupsModel)

    const columns: LemonTableColumns<FeatureFlagGroupType> = [
        {
            key: 'key',
            title: '',
            render: function Key(_, _item, index): JSX.Element {
                return <div className="font-semibold">{`Set ${index + 1}`}</div>
            },
        },
        {
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                const aggregationTargetName =
                    experiment.filters.aggregation_group_type_index != null
                        ? aggregationLabel(experiment.filters.aggregation_group_type_index).plural
                        : 'users'

                const releaseText = `${item.rollout_percentage}% of ${aggregationTargetName}`

                return (
                    <div>
                        {releaseText.startsWith('100% of') ? (
                            <LemonTag type="highlight">{releaseText}</LemonTag>
                        ) : (
                            releaseText
                        )}
                    </div>
                )
            },
        },
        {
            key: 'variant',
            title: 'Override',
            render: function Key(_, item): JSX.Element {
                return <div>{item.variant || '--'}</div>
            },
        },
    ]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Release conditions</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <LemonButton
                            icon={<IconFlag />}
                            onClick={() => {
                                openReleaseConditionsModal()
                                reportExperimentReleaseConditionsViewed(experiment.id)
                            }}
                            type="secondary"
                            size="xsmall"
                            className="font-semibold"
                        >
                            Manage release conditions
                        </LemonButton>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.feature_flag?.filters.groups || []} />
        </div>
    )
}
