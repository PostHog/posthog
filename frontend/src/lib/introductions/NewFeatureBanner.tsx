import React from 'react'
import { useValues } from 'kea'
import { LinkButton } from 'lib/components/LinkButton'
import { Link } from 'lib/components/Link'
import { userLogic } from 'scenes/userLogic'

export function NewFeatureBanner(): JSX.Element | null {
    const { upgradeLink } = useValues(userLogic)

    return (
        <div>
            <strong>🧪 Introducing Experimentation!</strong> Test changes to your product and how they impact your
            users.
            <LinkButton
                to={upgradeLink}
                className="NewFeatureAnnouncement__button"
                data-attr="site-banner-upgrade-experimentation"
            >
                Upgrade
            </LinkButton>
            <Link
                to="https://posthog.com/docs/user-guides/experimentation?utm_medium=in-product&utm_campaign=upgrade-site-banner-learn-more"
                target="_blank"
                ata-attr="site-banner-learn-more-experimentation"
                style={{ marginLeft: 8 }}
            >
                Learn more
            </Link>
        </div>
    )
}
