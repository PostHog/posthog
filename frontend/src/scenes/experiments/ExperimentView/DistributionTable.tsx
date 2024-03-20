import '../Experiment.scss'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { getSeriesColor } from 'lib/colors'
import { capitalizeFirstLetter } from 'lib/utils'
import { urls } from 'scenes/urls'

import { MultivariateFlagVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'

export function DistributionTable(): JSX.Element {
    const { experiment } = useValues(experimentLogic)

    const columns: LemonTableColumns<MultivariateFlagVariant> = [
        {
            className: 'w-1/3',
            key: 'key',
            title: 'Variant',
            render: function Key(_, item, index): JSX.Element {
                return (
                    <div className="flex items-center">
                        <div
                            className="w-2 h-2 rounded-full mr-2"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ backgroundColor: getSeriesColor(index + 1) }}
                        />
                        <span className="font-semibold">{capitalizeFirstLetter(item.key)}</span>
                    </div>
                )
            },
        },
        {
            className: 'w-1/3',
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                return <div>{`${item.rollout_percentage}%`}</div>
            },
        },
    ]

    return (
        <div>
            <div className="flex">
                <div className="w-1/2">
                    <h2 className="font-semibold text-lg">Distribution</h2>
                </div>

                <div className="w-1/2 flex flex-col justify-end">
                    <div className="ml-auto mb-2">
                        <Link
                            target="_blank"
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            Manage distribution
                        </Link>
                    </div>
                </div>
            </div>
            <LemonTable loading={false} columns={columns} dataSource={experiment.parameters.feature_flag_variants} />
        </div>
    )
}
