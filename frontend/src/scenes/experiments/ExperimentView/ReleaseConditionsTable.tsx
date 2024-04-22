import '../Experiment.scss'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { FeatureFlagGroupType } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function ReleaseConditionsTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)
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
                        <Link
                            target="_blank"
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            Manage release conditions
                        </Link>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.feature_flag?.filters.groups || []} />
        </div>
    )
}
