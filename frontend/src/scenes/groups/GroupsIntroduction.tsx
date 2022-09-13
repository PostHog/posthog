import React from 'react'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'
import { AvailableFeature } from '~/types'
import { Link } from '@posthog/lemon-ui'

interface Props {
    access: GroupsAccessStatus.NoAccess | GroupsAccessStatus.HasAccess | GroupsAccessStatus.HasGroupTypes
}

export function GroupsIntroduction({ access }: Props): JSX.Element {
    let header, subtext

    if (access === GroupsAccessStatus.NoAccess) {
        header = (
            <>
                Introducing <span className="highlight">Group Analytics</span>!
            </>
        )
        subtext = (
            <>
                Analyze how groups interact with your product as a whole instead of individual users (e.g. retention by
                companies instead of by users)
            </>
        )
    } else if (access === GroupsAccessStatus.HasAccess) {
        header = <>You're almost done!</>
        subtext = <>Learn how to track groups in your code</>
    } else {
        // HasGroupTypes
        header = <>Looks like you're tracking groups!</>
        subtext = <>Upgrade today to use groups in Insights.</>
    }

    return (
        <PayGatePage
            header={header}
            featureKey={AvailableFeature.GROUP_ANALYTICS}
            caption={subtext}
            docsLink="https://posthog.com/docs/user-guides/group-analytics"
            hideUpgradeButton={access === GroupsAccessStatus.HasAccess}
        />
    )
}

export function GroupIntroductionFooter(): JSX.Element {
    return (
        <div className="text-sm bg-side rounded p-2" style={{ maxWidth: '15rem' }}>
            Enter your payment information to use group analytics.{' '}
            <Link
                className="font-medium"
                to="/organization/billing"
                target="_blank"
                data-attr="group-analytics-upgrade"
            >
                Upgrade
            </Link>{' '}
            or{' '}
            <Link
                className="font-medium"
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                target="_blank"
                data-attr="group-analytics-learn-more"
            >
                Learn more
            </Link>
        </div>
    )
}
