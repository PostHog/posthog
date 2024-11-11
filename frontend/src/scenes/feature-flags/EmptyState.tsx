import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { router } from 'kea-router'
import { BuilderHog3 } from 'lib/components/hedgehogs'
import { FeatureFlagHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { Link } from 'lib/lemon-ui/Link'
import { ReactNode } from 'react'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

export const FeatureFlagsEmptyState = ({
    showProductIntroduction,
    filters,
}: {
    showProductIntroduction?: boolean
    filters?: ReactNode
}): JSX.Element => {
    if (showProductIntroduction) {
        return (
            <ProductIntroduction
                productName="Feature flags"
                productKey={ProductKey.FEATURE_FLAGS}
                thingName="feature flag"
                description="Use feature flags to safely deploy and roll back new features in an easy-to-manage way. Roll variants out to certain groups, a percentage of users, or everyone all at once."
                docsURL="https://posthog.com/docs/feature-flags/manual"
                action={() => router.actions.push(urls.featureFlag('new'))}
                isEmpty
                customHog={FeatureFlagHog}
            />
        )
    }

    return (
        <>
            {filters}
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
        </>
    )
}
