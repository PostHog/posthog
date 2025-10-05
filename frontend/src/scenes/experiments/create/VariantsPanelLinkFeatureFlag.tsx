import { IconToggle } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link } from 'lib/lemon-ui/Link'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import type { FeatureFlagType } from '~/types'

interface VariantsPanelLinkFeatureFlagProps {
    linkedFeatureFlag: FeatureFlagType | null
    setShowFeatureFlagSelector: (show: boolean) => void
}

export const VariantsPanelLinkFeatureFlag = ({
    linkedFeatureFlag,
    setShowFeatureFlagSelector,
}: VariantsPanelLinkFeatureFlagProps): JSX.Element => {
    return (
        <div>
            <label className="text-sm font-semibold">Selected Feature Flag</label>
            {!linkedFeatureFlag ? (
                <div className="mt-2 p-8 border border-dashed rounded-lg bg-bg-light flex flex-col items-center gap-3">
                    <div className="flex items-center gap-2">
                        <IconToggle className="text-muted text-2xl" />
                        <div className="text-base font-semibold">No feature flag selected</div>
                    </div>
                    <div className="text-sm text-muted-alt text-center">
                        Select an existing multivariate feature flag to use with this experiment
                    </div>
                    <LemonButton type="primary" size="small" onClick={() => setShowFeatureFlagSelector(true)}>
                        Select Feature Flag
                    </LemonButton>
                </div>
            ) : (
                <div className="mt-2 border border-border rounded-lg bg-bg-light shadow-sm p-6">
                    <div className="flex justify-between items-start gap-6">
                        <div className="flex-1 space-y-3">
                            <div className="flex items-center gap-2">
                                <IconToggle className="text-lg" />
                                <div className="font-bold text-lg">{linkedFeatureFlag.key}</div>
                                <Link
                                    to={urls.featureFlag(linkedFeatureFlag.id as number)}
                                    target="_blank"
                                    className="flex items-center hover:text-link"
                                >
                                    <IconOpenInNew />
                                </Link>
                            </div>
                            {linkedFeatureFlag.name && (
                                <div className="text-sm text-muted-alt">{linkedFeatureFlag.name}</div>
                            )}
                            <div className="flex items-center gap-3">
                                <span className="text-2xs uppercase tracking-wide font-semibold text-muted">
                                    Variants
                                </span>
                                <div className="flex flex-wrap gap-1">
                                    {linkedFeatureFlag.filters?.multivariate?.variants?.map(({ key }) => (
                                        <LemonTag key={key} type="default">
                                            {key}
                                        </LemonTag>
                                    )) || []}
                                </div>
                            </div>
                        </div>
                        <LemonButton type="secondary" size="small" onClick={() => setShowFeatureFlagSelector(true)}>
                            Change
                        </LemonButton>
                    </div>
                </div>
            )}
        </div>
    )
}
