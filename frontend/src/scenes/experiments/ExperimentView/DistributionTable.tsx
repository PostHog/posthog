import '../Experiment.scss'

import { IconBalance, IconFlag } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonDialog,
    LemonInput,
    LemonModal,
    LemonTable,
    LemonTableColumns,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { featureFlagLogic, FeatureFlagLogicProps } from 'scenes/feature-flags/featureFlagLogic'

import { Experiment, MultivariateFlagVariant } from '~/types'

import { experimentLogic } from '../experimentLogic'
import { VariantTag } from './components'
import { VariantScreenshot } from './VariantScreenshot'

export function DistributionModal({ experimentId }: { experimentId: Experiment['id'] }): JSX.Element {
    const { experiment, experimentLoading, isDistributionModalOpen } = useValues(experimentLogic({ experimentId }))
    const { closeDistributionModal } = useActions(experimentLogic({ experimentId }))

    const _featureFlagLogic = featureFlagLogic({ id: experiment.feature_flag?.id ?? null } as FeatureFlagLogicProps)
    const { featureFlag, areVariantRolloutsValid, variantRolloutSum } = useValues(_featureFlagLogic)
    const { setFeatureFlagFilters, distributeVariantsEqually, saveSidebarExperimentFeatureFlag } =
        useActions(_featureFlagLogic)

    const handleRolloutPercentageChange = (index: number, value: number | undefined): void => {
        if (!featureFlag?.filters?.multivariate || !value) {
            return
        }

        const updatedVariants = featureFlag.filters.multivariate.variants.map((variant, i) =>
            i === index ? { ...variant, rollout_percentage: value } : variant
        )

        setFeatureFlagFilters(
            {
                ...featureFlag.filters,
                multivariate: { ...featureFlag.filters.multivariate, variants: updatedVariants },
            },
            null
        )
    }

    return (
        <LemonModal
            isOpen={isDistributionModalOpen}
            onClose={closeDistributionModal}
            width={600}
            title="Change experiment distribution"
            footer={
                <div className="flex items-center gap-2">
                    <LemonButton type="secondary" onClick={closeDistributionModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        onClick={() => {
                            saveSidebarExperimentFeatureFlag(featureFlag)
                            closeDistributionModal()
                        }}
                        type="primary"
                        loading={experimentLoading}
                        disabled={!areVariantRolloutsValid}
                    >
                        Save
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <LemonBanner type="info">
                    Adjusting variant distribution may impact the validity of your results. Adjust only if you're aware
                    of how changes will affect your experiment.
                </LemonBanner>

                <div>
                    <div className="flex justify-between items-center mb-2">
                        <h3 className="font-semibold mb-0">Variant Distribution</h3>
                        <LemonButton
                            size="small"
                            onClick={distributeVariantsEqually}
                            tooltip="Redistribute variant rollout percentages equally"
                            icon={<IconBalance />}
                        >
                            Distribute equally
                        </LemonButton>
                    </div>

                    <LemonTable
                        dataSource={featureFlag?.filters?.multivariate?.variants || []}
                        columns={[
                            {
                                title: 'Variant',
                                dataIndex: 'key',
                                render: (value) => <span className="font-semibold">{value}</span>,
                            },
                            {
                                title: 'Rollout Percentage',
                                dataIndex: 'rollout_percentage',
                                render: (_, record, index) => (
                                    <LemonInput
                                        type="number"
                                        value={record.rollout_percentage}
                                        onChange={(value) => handleRolloutPercentageChange(index, value)}
                                        min={0}
                                        max={100}
                                        suffix={<span>%</span>}
                                    />
                                ),
                            },
                        ]}
                    />

                    {!areVariantRolloutsValid && (
                        <p className="text-danger mt-2">
                            Percentage rollouts must sum to 100 (currently {variantRolloutSum}).
                        </p>
                    )}
                </div>
            </div>
        </LemonModal>
    )
}

export function DistributionTable(): JSX.Element {
    const { openDistributionModal } = useActions(experimentLogic)
    const { experimentId, experiment, experimentResults } = useValues(experimentLogic)
    const { reportExperimentReleaseConditionsViewed } = useActions(experimentLogic)

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
                    <div className="my-2 grid grid-cols-2 content-center">
                        <VariantScreenshot
                            variantKey={item.key}
                            rolloutPercentage={item.rollout_percentage}
                            mediaTypeKey="desktop"
                        />
                        <VariantScreenshot
                            variantKey={item.key}
                            rolloutPercentage={item.rollout_percentage}
                            mediaTypeKey="mobile"
                        />
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
                                openDistributionModal()
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
