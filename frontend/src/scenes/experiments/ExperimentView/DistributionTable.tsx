import '../Experiment.scss'

import { IconFlag } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { MultivariateFlagVariant, SidePanelTab } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'
import { VariantScreenshot } from './VariantScreenshot'

export function DistributionTable(): JSX.Element {
    const { experimentId, experiment, experimentResults } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed } = useActions(experimentLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

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
        {
            className: 'w-1/3',
            key: 'variant_screenshot',
            title: 'Screenshot',
            render: function Key(_, item): JSX.Element {
                return (
                    <div className="my-2">
                        <VariantScreenshot variantKey={item.key} rolloutPercentage={item.rollout_percentage} />
                    </div>
                )
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
                            Manage distribution
                        </LemonButton>
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
