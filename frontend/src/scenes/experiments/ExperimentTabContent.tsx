import { useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import type { FeatureFlagType } from '~/types'

import { CreateDraftExperimentCard } from './ExperimentTabContent/CreateDraftExperimentCard'
import { RelatedExperimentsTable } from './ExperimentTabContent/RelatedExperimentsTable'
import { experimentTabLogic } from './experimentTabLogic'
import { getFlagVariants } from './utils'

type ExperimentTabContentProps = {
    featureFlag: FeatureFlagType
    multipleExperimentsBannerMessage: React.ReactNode
}

export const ExperimentTabContent = ({
    featureFlag,
    multipleExperimentsBannerMessage,
}: ExperimentTabContentProps): JSX.Element | null => {
    /**
     * we only operate with existing feature flags, so id will never be null.
     */
    const { relatedExperiments, relatedExperimentsLoading } = useValues(
        experimentTabLogic({ featureFlagId: featureFlag.id! })
    )

    const variants = getFlagVariants(featureFlag)
    const isValidMultivariateFlag = variants.length > 1 && variants.some((variant) => variant.key === 'control')

    if (!isValidMultivariateFlag) {
        return (
            <div className="space-y-6">
                <LemonBanner type="warning">
                    <div className="flex flex-col gap-3">
                        <div>
                            Experiments require a multivariate flag with multiple variants and a control variant.&nbsp;
                            <Link to="https://posthog.com/docs/experiments/creating-an-experiment">
                                Learn more in the docs
                            </Link>
                            .
                        </div>
                    </div>
                </LemonBanner>
            </div>
        )
    }

    return (
        <div className="space-y-4">
            {relatedExperimentsLoading ? (
                <div className="border rounded p-4 bg-bg-light space-y-3">
                    <LemonSkeleton className="h-6 w-1/2" />
                    <LemonSkeleton className="h-4 w-3/4" />
                    <LemonSkeleton className="h-9 w-full" />
                    <LemonSkeleton className="h-9 w-32" />
                </div>
            ) : (
                relatedExperiments.length === 0 && <CreateDraftExperimentCard featureFlag={featureFlag} />
            )}
            <RelatedExperimentsTable
                relatedExperiments={relatedExperiments}
                relatedExperimentsLoading={relatedExperimentsLoading}
                multipleExperimentsBannerMessage={multipleExperimentsBannerMessage}
            />
        </div>
    )
}
