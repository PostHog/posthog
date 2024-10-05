import { LemonBanner, LemonButton, LemonDivider, LemonInput, LemonTable, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect, useMemo } from 'react'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { featureFlagLogic, FeatureFlagLogicProps } from 'scenes/feature-flags/featureFlagLogic'
import { FeatureFlagReleaseConditions } from 'scenes/feature-flags/FeatureFlagReleaseConditions'

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

    const experimentId = useMemo(() => {
        const match = currentLocation.pathname.match(/\/experiments\/(\d+)/)
        return match ? parseInt(match[1]) : null
    }, [currentLocation.pathname])

    const { experiment } = useValues(experimentLogic({ experimentId: experimentId ?? 'new' }))

    // CLEAN UP NAMING ETC
    const logic = featureFlagLogic({ id: experiment.feature_flag?.id ?? null } as FeatureFlagLogicProps)
    const { featureFlag, areVariantRolloutsValid, variantRolloutSum, featureFlagLoading } = useValues(logic)
    const { setFeatureFlagFilters, saveSidebarExperimentFeatureFlag, distributeVariantsEqually } = useActions(logic)

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

    const variants = featureFlag?.filters?.multivariate?.variants || []

    if (featureFlagLoading || !featureFlag.id) {
        return (
            <div className="flex items-center justify-center h-full">
                <Spinner className="text-3xl" />
            </div>
        )
    }

    return (
        <div className="space-y-4 p-2">
            <LemonBanner type="info">
                Here you can adjust the experiment's release conditions and variant rollout percentages. The default
                settings are generally suitable, so proceed with caution. Modifying these parameters can significantly
                impact your experiment's results. Ensure you fully understand the implications of any changes before
                saving.
            </LemonBanner>
            <div>
                <h4 className="l3">Feature flag variants</h4>
                <LemonTable
                    dataSource={variants}
                    columns={[
                        {
                            title: 'Variant Key',
                            dataIndex: 'key',
                            key: 'key',
                            render: (value) => <span className="font-semibold">{value}</span>,
                        },
                        {
                            title: (
                                <div className="flex items-center justify-between space-x-2">
                                    <span>Rollout Percentage</span>
                                    <LemonButton type="secondary" size="xsmall" onClick={distributeVariantsEqually}>
                                        Redistribute
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

            <LemonDivider />

            <div>
                <FeatureFlagReleaseConditions
                    id={`${experiment.feature_flag?.id}`}
                    filters={featureFlag?.filters ?? []}
                    onChange={setFeatureFlagFilters}
                />
            </div>

            <div>
                <LemonButton
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
