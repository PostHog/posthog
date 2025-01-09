import { IconPlusSmall } from '@posthog/icons'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function FeatureManagementEmptyState(): JSX.Element {
    return (
        <div className="text-center" data-attr="feature-flag-empty-state-filtered">
            <div className="w-40 m-auto">
                <BuilderHog3 className="w-full h-full" />
            </div>
            <h2>No features created yet</h2>
            <p>Start your first big feature rollout today.</p>

            <div className="flex justify-center">
                <Link to={urls.featureManagementNew()}>
                    <LemonButton type="primary" data-attr="empty-state-add-feature-button" icon={<IconPlusSmall />}>
                        New feature
                    </LemonButton>
                </Link>
            </div>
        </div>
    )
}
