import '../Experiment.scss'

import { IconFlag } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { groupsModel } from '~/models/groupsModel'
import { FeatureFlagGroupType, SidePanelTab } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function ReleaseConditionsTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed } = useActions(experimentLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { openSidePanel } = useActions(sidePanelStateLogic)

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
                                openSidePanel(SidePanelTab.ExperimentFeatureFlag)
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
