import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export const FeatureFlagsEmptyState = (): JSX.Element => (
    <div className="text-center">
        <div className="w-40 m-auto">
            <BuilderHog3 className="w-full h-full" />
        </div>
        <h2>There are no feature flags matching these filters</h2>
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
