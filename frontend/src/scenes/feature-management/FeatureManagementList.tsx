import { IconPlusSmall } from '@posthog/icons'
import { LemonSkeleton, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { featureManagementLogic } from './featureManagementLogic'

export function FeatureManagementList(): JSX.Element {
    const { activeFeatureId, features, featuresLoading } = useValues(featureManagementLogic)
    const { setActiveFeatureId } = useActions(featureManagementLogic)

    const header = (
        <div className="flex align-middle justify-between">
            <h2>Features</h2>
            <Link to={urls.featureManagementNew()}>
                <LemonButton type="primary" data-attr="add-feature-button" icon={<IconPlusSmall />}>
                    New feature
                </LemonButton>
            </Link>
        </div>
    )

    return (
        <div className="flex flex-col gap-4">
            {header}
            <div className="flex flex-col gap-1">
                {featuresLoading && (
                    <>
                        <LemonSkeleton className="w-full h-8" active />
                        <LemonSkeleton className="w-full h-8" active />
                        <LemonSkeleton className="w-full h-8" active />
                    </>
                )}
                {features?.results.map((feature) => (
                    <div key={feature.id}>
                        <LemonButton
                            onClick={() => setActiveFeatureId(feature.id)}
                            size="small"
                            fullWidth
                            active={activeFeatureId === feature.id}
                        >
                            <span className="truncate">{feature.name}</span>
                        </LemonButton>
                    </div>
                ))}
            </div>
        </div>
    )
}
