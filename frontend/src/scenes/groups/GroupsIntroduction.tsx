import { Link } from '@posthog/lemon-ui'
import { PayGatePage } from 'lib/components/PayGatePage/PayGatePage'
import { GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

import { AvailableFeature } from '~/types'

interface Props {
    access: GroupsAccessStatus.NoAccess | GroupsAccessStatus.HasAccess | GroupsAccessStatus.HasGroupTypes
}

export function GroupsIntroduction({ access }: Props): JSX.Element {
    let header, subtext

    if (access === GroupsAccessStatus.NoAccess) {
        header = (
            <>
                Introducing <span className="highlight">Group&nbsp;Analytics</span>!
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

export function GroupIntroductionFooter({ needsUpgrade }: { needsUpgrade: boolean }): JSX.Element {
    return (
        <div className="text-sm bg-mid rounded p-2 max-w-60">
            {needsUpgrade ? (
                <>
                    Track usage of groups of users with Group&nbsp;Analytics.{' '}
                    <Link
                        className="font-medium"
                        to="/organization/billing"
                        target="_blank"
                        data-attr="group-analytics-upgrade"
                    >
                        Upgrade now
                    </Link>{' '}
                    or{' '}
                    <Link
                        className="font-medium"
                        to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                        target="_blank"
                        data-attr="group-analytics-learn-more"
                    >
                        learn more
                    </Link>
                    .
                </>
            ) : (
                <>
                    You can now use Group Analytics. See{' '}
                    <Link
                        className="font-medium"
                        to="https://posthog.com/manual/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-get-started"
                        target="_blank"
                        data-attr="group-analytics-get-started"
                    >
                        how to get started
                    </Link>
                    .
                </>
            )}
        </div>
    )
}
