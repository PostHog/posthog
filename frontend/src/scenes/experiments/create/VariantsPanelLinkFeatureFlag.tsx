import { IconToggle } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
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
        <div className="max-w-2xl">
            <label className="text-sm font-semibold">Selected Feature Flag</label>
            {!linkedFeatureFlag ? (
                <div className="mt-2 p-4 border border-dashed rounded bg-surface-light">
                    <div className="text-center">
                        <div className="text-sm text-muted mb-2">No feature flag selected</div>
                        <LemonButton type="primary" onClick={() => setShowFeatureFlagSelector(true)}>
                            Select Feature Flag
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <div className="mt-2 border-2 border-primary-light rounded-lg bg-primary-highlight p-4">
                    <div className="flex justify-between items-start gap-4">
                        <div className="flex-1">
                            <div className="flex items-center gap-2">
                                <IconToggle className="text-primary" />
                                <div className="font-semibold text-base">{linkedFeatureFlag.key}</div>
                                <Link
                                    to={urls.featureFlag(linkedFeatureFlag.id as number)}
                                    target="_blank"
                                    className="flex items-center text-primary hover:text-primary-dark"
                                >
                                    <IconOpenInNew className="text-lg" />
                                </Link>
                            </div>
                            {linkedFeatureFlag.name && (
                                <div className="text-muted-alt mt-1">{linkedFeatureFlag.name}</div>
                            )}
                            <div className="mt-3 flex items-center gap-4">
                                <div className="flex items-center gap-2">
                                    <span className="text-xs font-medium text-muted">VARIANTS:</span>
                                    <div className="flex gap-1">
                                        {linkedFeatureFlag.filters?.multivariate?.variants?.map(({ key }) => (
                                            <span
                                                key={key}
                                                className="inline-flex items-center px-2 py-0.5 rounded-md bg-bg-light text-xs font-medium"
                                            >
                                                {key}
                                            </span>
                                        )) || []}
                                    </div>
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
