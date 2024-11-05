import '../Experiment.scss'

import { IconFlag } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInApp } from 'lib/lemon-ui/icons'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { MultivariateFlagVariant, SidePanelTab } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'
import { VariantScreenshot } from './VariantScreenshot'

export function DistributionTable(): JSX.Element {
    const { experimentId, experiment, experimentResults } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed } = useActions(experimentLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    const onSelectElement = (variant: string): void => {
        LemonDialog.open({
            title: 'Select a domain',
            description: 'Choose the domain on which to preview this experiment variant',
            content: (
                <>
                    <AuthorizedUrlList
                        query={'?__experiment_id=' + experiment?.id + '&__experiment_variant=' + variant}
                        experimentId={experiment?.id}
                        type={AuthorizedUrlListType.WEB_EXPERIMENTS}
                    />
                </>
            ),
            primaryButton: {
                children: 'Close',
                type: 'secondary',
            },
        })
    }
    const className = experiment?.type === 'web' ? 'w-1/2.5' : 'w-1/3'
    const columns: LemonTableColumns<MultivariateFlagVariant> = [
        {
            className: className,
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
            className: className,
            key: 'rollout_percentage',
            title: 'Rollout',
            render: function Key(_, item): JSX.Element {
                return <div>{`${item.rollout_percentage}%`}</div>
            },
        },
        {
            className: className,
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

    if (experiment.type === 'web') {
        columns.push({
            className: className,
            key: 'preview_web_experiment',
            title: 'Preview',
            render: function Key(_, item): JSX.Element {
                return (
                    <div className="my-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={(e) => {
                                e.preventDefault()
                                onSelectElement(item.key)
                            }}
                            sideIcon={<IconOpenInApp />}
                        >
                            Preview variant
                        </LemonButton>
                    </div>
                )
            },
        })
    }

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
