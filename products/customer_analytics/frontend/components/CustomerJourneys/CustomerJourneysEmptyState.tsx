import { useValues } from 'kea'
import { router } from 'kea-router'

import { ExplorerHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

const BASE_DESCRIPTION = 'Track how customers move through your product by building funnel-based journeys.'

export function CustomerJourneysEmptyState({ embedded }: { embedded?: boolean }): JSX.Element {
    const { groupsEnabled } = useValues(groupsAccessLogic)
    const accessControlDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.CustomerAnalytics,
        AccessControlLevel.Editor
    )

    const description = embedded
        ? BASE_DESCRIPTION
        : groupsEnabled
          ? `${BASE_DESCRIPTION} Journeys are also visible on each person and group profile.`
          : `${BASE_DESCRIPTION} Journeys are also visible on each person's profile.`

    return (
        <ProductIntroduction
            productName="Customer journeys"
            thingName="journey"
            description={description}
            action={() => router.actions.push(urls.customerJourneyTemplates())}
            disabledReason={accessControlDisabledReason ?? undefined}
            customHog={ExplorerHog}
            className={embedded ? 'border-0' : undefined}
            isEmpty
        />
    )
}
