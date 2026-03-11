import { LemonBanner, Link } from '@posthog/lemon-ui'

import type { FeatureFlagType } from '~/types'

import { CreateDraftExperimentCard } from './ExperimentTabContent/CreateDraftExperimentCard'
import { RelatedExperimentsTable } from './ExperimentTabContent/RelatedExperimentsTable'

type ExperimentTabContentProps = {
    featureFlag: FeatureFlagType
    multipleExperimentsBannerMessage: React.ReactNode
}

export const ExperimentTabContent = ({
    featureFlag,
    multipleExperimentsBannerMessage,
}: ExperimentTabContentProps): JSX.Element | null => {
    const isValidMultivariateFlag =
        featureFlag.filters.multivariate &&
        featureFlag.filters.multivariate.variants.length > 1 &&
        featureFlag.filters.multivariate.variants.some((variant) => variant.key === 'control')

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
            <CreateDraftExperimentCard featureFlag={featureFlag} />
            <RelatedExperimentsTable
                featureFlag={featureFlag}
                multipleExperimentsBannerMessage={multipleExperimentsBannerMessage}
            />
        </div>
    )
}
