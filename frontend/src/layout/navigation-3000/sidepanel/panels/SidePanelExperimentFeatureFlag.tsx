import { IconBalance } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonTable, Link, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { featureFlagLogic, FeatureFlagLogicProps } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'
import { urls } from 'scenes/urls'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

export const SidePanelExperimentFeatureFlag = (): JSX.Element => {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { currentLocation } = useValues(router)

    useEffect(() => {
        // Side panel state is persisted in local storage, so we need to check if we're on the experiment page,
        // otherwise close the side panel
        const isExperimentPath = /^\/project\/[0-9]+\/experiments\/[0-9]+/.test(currentLocation.pathname)
        if (!isExperimentPath) {
            closeSidePanel()
        }
    }, [currentLocation, closeSidePanel])

    // Retrieve experiment ID from URL
    const experimentId = useMemo(() => {
        const match = currentLocation.pathname.match(/\/experiments\/(\d+)/)
        return match ? parseInt(match[1]) : null
    }, [currentLocation.pathname])

    const { experiment } = useValues(experimentLogic({ experimentId: experimentId ?? 'new' }))

    const _featureFlagLogic = featureFlagLogic({ id: experiment.feature_flag?.id ?? null } as FeatureFlagLogicProps)
    const { featureFlag, areVariantRolloutsValid, variantRolloutSum, featureFlagLoading } = useValues(_featureFlagLogic)
    const { setFeatureFlagFilters, saveSidebarExperimentFeatureFlag, distributeVariantsEqually } =
        useActions(_featureFlagLogic)

    const variants = featureFlag?.filters?.multivariate?.variants || []

    const handleRolloutPercentageChange = (index: number, value: number | undefined): void => {
        if (!featureFlag?.filters?.multivariate || !value) {
            return
        }

        const updatedVariants = featureFlag.filters.multivariate.variants.map((variant, i) =>
            i === index ? { ...variant, rollout_percentage: value } : variant
        )

        const updatedFilters = {
            ...featureFlag.filters,
            multivariate: { ...featureFlag.filters.multivariate, variants: updatedVariants },
        }

        setFeatureFlagFilters(updatedFilters, null)
    }

    if (featureFlagLoading || !featureFlag.id) {
        return (
            <div className="flex items-center justify-center h-full">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    return (
        <div className="space-y-6 p-2">
            <LemonBanner type="info">
                <div className="space-y-3">
                    <div>
                        Adjusting variant distribution or user targeting may impact the validity of your results. Adjust
                        only if you're aware of how changes will affect your experiment.
                    </div>
                    <div>
                        For full feature flag settings, go to{' '}
                        <Link
                            target="_blank"
                            className="font-semibold"
                            to={experiment.feature_flag ? urls.featureFlag(experiment.feature_flag.id) : undefined}
                        >
                            {experiment.feature_flag?.key}
                        </Link>{' '}
                        .
                    </div>
                </div>
            </LemonBanner>
            <div>
                <h3 className="l3">Experiment variants</h3>
                <LemonTable
                    dataSource={variants}
                    columns={[
                        {
                            title: 'Variant Key',
                            dataIndex: 'key',
                            key: 'key',
                            render: (value) => <span className="font-semibold">{value}</span>,
                            width: '50%',
                        },
                        {
                            title: (
                                <div className="flex items-center justify-between space-x-2">
                                    <span>Rollout Percentage</span>
                                    <LemonButton
                                        onClick={distributeVariantsEqually}
                                        tooltip="Redistribute variant rollout percentages equally"
                                    >
                                        <IconBalance />
                                    </LemonButton>
                                </div>
                            ),
                            dataIndex: 'rollout_percentage',
                            key: 'rollout_percentage',
                            render: (_, record, index) => (
                                <LemonInput
                                    type="number"
                                    value={record.rollout_percentage}
                                    onChange={(changedValue) => {
                                        if (changedValue !== null) {
                                            const valueInt =
                                                changedValue !== undefined ? parseInt(changedValue.toString()) : 0
                                            if (!isNaN(valueInt)) {
                                                handleRolloutPercentageChange(index, changedValue)
                                            }
                                        }
                                    }}
                                    min={0}
                                    max={100}
                                    suffix={<span>%</span>}
                                />
                            ),
                        },
                    ]}
                />
                {variants.length > 0 && !areVariantRolloutsValid && (
                    <p className="text-danger">
                        Percentage rollouts for variants must sum to 100 (currently {variantRolloutSum}
                        ).
                    </p>
                )}
            </div>

            <FeatureFlagReleaseConditions
                id={`${experiment.feature_flag?.id}`}
                filters={featureFlag?.filters ?? []}
                onChange={setFeatureFlagFilters}
            />
            <LemonDivider />
            <div>
                <LemonButton
                    className="-mt-4"
                    type="primary"
                    onClick={() => {
                        saveSidebarExperimentFeatureFlag(featureFlag)
                    }}
                >
                    Save
                </LemonButton>
            </div>
        </div>
    )
}
