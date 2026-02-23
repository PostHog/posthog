import { useActions, useValues } from 'kea'

import { getSeriesColor } from 'lib/colors'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'
import { alphabet, formatPercentage } from 'lib/utils'

import type { FeatureFlagType } from '~/types'

import { TrafficPreview, VariantsPanelCreateFeatureFlag } from '../../ExperimentForm/VariantsPanelCreateFeatureFlag'
import { experimentWizardLogic } from '../experimentWizardLogic'

const ReadOnlyVariantsStep = ({ flag }: { flag: FeatureFlagType }): JSX.Element => {
    const variants = flag.filters?.multivariate?.variants || []
    const rolloutPercentage = flag.filters.groups?.[0]?.rollout_percentage ?? 100
    const variantRolloutSum = variants.reduce((sum, { rollout_percentage }) => sum + rollout_percentage, 0)

    return (
        <>
            <LemonBanner type="info">
                For linked feature flags, this step is read-only. You can adjust the feature flag itself after saving
                the experiment.
            </LemonBanner>

            <div className="flex gap-4 flex-col">
                <div className="flex-1">
                    <div className="font-semibold mb-2">Variants</div>
                    <div className="border border-primary rounded p-4">
                        <table className="w-full">
                            <thead>
                                <tr className="text-sm font-bold">
                                    <td className="w-8" />
                                    <td>Variant key</td>
                                    <td>Split</td>
                                </tr>
                            </thead>
                            <tbody>
                                {variants.map((variant, index) => (
                                    <tr key={variant.key}>
                                        <td className="py-2 pr-2">
                                            <div className="flex items-center justify-center">
                                                <Lettermark name={alphabet[index]} color={LettermarkColor.Gray} />
                                            </div>
                                        </td>
                                        <td className="py-2 pr-2">
                                            <div className="flex items-center h-10 px-2 font-medium">{variant.key}</div>
                                        </td>
                                        <td className="py-2">
                                            <div className="flex items-center h-10 px-2">
                                                {formatPercentage(variant.rollout_percentage, { compact: true })}
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div className="flex-1">
                    <div className="font-semibold mb-2">Rollout</div>
                    <div className="border border-primary rounded p-4 flex flex-col gap-5">
                        <div className="flex items-center justify-between">
                            <h4 className="m-0">Rollout percent</h4>
                            <div className="flex items-center gap-1 text-sm font-semibold">
                                <span
                                    className="inline-block w-3 h-3 rounded-sm"
                                    style={{ backgroundColor: getSeriesColor(0) }}
                                />
                                {rolloutPercentage}%
                            </div>
                        </div>
                        <TrafficPreview
                            variants={variants}
                            rolloutPercentage={rolloutPercentage}
                            areVariantRolloutsValid={variantRolloutSum === 100}
                        />
                    </div>
                </div>
            </div>
        </>
    )
}

export function VariantsStep(): JSX.Element {
    const { experiment, linkedFeatureFlag } = useValues(experimentWizardLogic)
    const { setFeatureFlagConfig } = useActions(experimentWizardLogic)

    return (
        <div className="space-y-6">
            <div>
                <h3 className="text-lg font-semibold">Who sees which variant?</h3>
            </div>
            {linkedFeatureFlag ? (
                <ReadOnlyVariantsStep flag={linkedFeatureFlag} />
            ) : (
                <VariantsPanelCreateFeatureFlag
                    experiment={experiment}
                    onChange={setFeatureFlagConfig}
                    layout="vertical"
                />
            )}
        </div>
    )
}
