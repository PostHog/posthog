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
            <h2>There are no feature flags matching these filters.</h2>
            <p>Refine your keyword search, or try using other filters such as type, status or created by.</p>

            <div className="flex justify-center">
                <Link to={urls.featureFlag('new')}>
                    <LemonButton type="primary" data-attr="add-insight-button-empty-state" icon={<IconPlusSmall />}>
                        New feature flag
                    </LemonButton>
                </Link>
            </div>
        </div>
    )
}
