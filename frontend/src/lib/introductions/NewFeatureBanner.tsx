import React from 'react'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { userLogic } from 'scenes/userLogic'
import { LemonButton } from '@posthog/lemon-ui'

export function NewFeatureBanner(): JSX.Element | null {
    const { upgradeLink } = useValues(userLogic)

    return (
        <div className="flex items-center">
            <strong>🧪 Introducing Experimentation!</strong> Test changes to your product and how they impact your
            users.
            <LemonButton to={upgradeLink} type="secondary" size="small" data-attr="site-banner-upgrade-experimentation">
                Upgrade
            </LemonButton>
            <Link
                to="https://posthog.com/docs/user-guides/experimentation?utm_medium=in-product&utm_campaign=upgrade-site-banner-learn-more"
                target="_blank"
                ata-attr="site-banner-learn-more-experimentation"
                className="ml-2"
            >
                Learn more
            </Link>
        </div>
    )
}
