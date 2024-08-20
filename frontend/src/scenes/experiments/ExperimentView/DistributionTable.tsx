import '../Experiment.scss'

import { LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { urls } from 'scenes/urls'

import { MultivariateFlagVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'

export function DistributionTable(): JSX.Element {
    const { experimentId, experiment, experimentResults } = useValues(experimentLogic)

    const columns: LemonTableColumns<MultivariateFlagVariant> = [
        {
            className: 'w-1/3',
            key: 'key',
            title: 'Variant',
            render: function Key(_, item): JSX.Element {
                if (!experimentResults || !experimentResults.insight) {
                    return <span className="font-semibold">{item.key}</span>
                }
                return <VariantTag experimentId={experimentId} variantKey={item.key} />
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
            <LemonTable
                loading={false}
                columns={columns}
                dataSource={experiment.feature_flag?.filters.multivariate?.variants || []}
            />
        </div>
    )
}
