import { IconOpenSidebar } from '@posthog/icons'
import { LemonButton, Link } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'

import { AvailableFeature } from '~/types'

export function GroupsIntroduction(): JSX.Element {
    return (
        <PayGateMini
            feature={AvailableFeature.GROUP_ANALYTICS}
            className="py-8"
            docsLink="https://posthog.com/docs/user-guides/group-analytics"
        >
            <div className="mt-4 flex min-h-56 flex-col items-center justify-center rounded-lg border py-8 text-center">
                <h2 className="mb-2 text-2xl font-semibold">Start tracking groups</h2>
                <div className="max-w-140">
                    Get a 360&deg; view of how companies or teams use your product. Use the SDK to create a group, and
                    then include the group identifier in the event&nbsp;properties.
                </div>
                <div className="mt-4 w-80 max-w-[90%]">
                    <LemonButton
                        type="primary"
                        to={`https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=${AvailableFeature.GROUP_ANALYTICS}-upgrade-learn-more`}
                        targetBlank
                        center
                        data-attr={`${AvailableFeature.GROUP_ANALYTICS}-learn-more`}
                    >
                        Learn more <IconOpenSidebar className="ml-4" />
                    </LemonButton>
                </div>
            </div>
        </PayGateMini>
    )
}

export function GroupIntroductionFooter({ needsUpgrade }: { needsUpgrade: boolean }): JSX.Element {
    return (
        <div className="bg-primary max-w-60 rounded p-2 text-sm">
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
                        to="https://posthog.com/docs/product-analytics/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-get-started"
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
