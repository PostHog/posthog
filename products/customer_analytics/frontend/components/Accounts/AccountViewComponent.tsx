import { userHasAccess } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { CustomerTasksTabContent } from '../CustomerTasks/CustomerTasksTabContent'
import { AccountEventStreamToggle } from '../EventStream/AccountEventStreamToggle'
import { AccountBillingExpansion } from './AccountBillingExpansion'
import { AccountConversationsExpansion } from './AccountConversationsExpansion'
import { AccountFeatureRequestsExpansion } from './AccountFeatureRequestsExpansion'
import { AccountMeetingsExpansion } from './AccountMeetingsExpansion'
import { AccountNotesExpansion } from './AccountNotesExpansion'
import { AccountOpportunitiesExpansion } from './AccountOpportunitiesExpansion'
import { AccountRelatedUsersExpansion } from './AccountRelatedUsersExpansion'
import { AccountRelationshipsExpansion } from './AccountRelationshipsExpansion'
import type { AccountViewComponentKind } from './accountViewComponents'

interface AccountViewComponentProps {
    kind: AccountViewComponentKind
    accountId: string
    externalId: string
    embedded?: boolean
}

export function AccountViewComponent({
    kind,
    accountId,
    externalId,
    embedded = true,
}: AccountViewComponentProps): JSX.Element {
    switch (kind) {
        case 'notes':
            return <AccountNotesExpansion accountId={accountId} embedded={embedded} />
        case 'tasks':
            return (
                <CustomerTasksTabContent
                    accountId={accountId}
                    canCreate={userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Editor)}
                    canViewAll={userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Viewer)}
                    embedded={embedded}
                />
            )
        case 'users':
            return <AccountRelatedUsersExpansion externalId={externalId} embedded={embedded} />
        case 'relationships':
            return <AccountRelationshipsExpansion accountId={accountId} embedded={embedded} />
        case 'feature_requests':
            return <AccountFeatureRequestsExpansion accountId={accountId} embedded={embedded} />
        case 'usage':
            return <AccountBillingExpansion accountId={accountId} externalId={externalId} kind="usage" />
        case 'spend':
            return <AccountBillingExpansion accountId={accountId} externalId={externalId} kind="spend" />
        case 'opportunities':
            return <AccountOpportunitiesExpansion accountId={accountId} embedded={embedded} />
        case 'conversations':
            return <AccountConversationsExpansion accountId={accountId} embedded={embedded} />
        case 'meetings':
            return <AccountMeetingsExpansion accountId={accountId} embedded={embedded} />
        case 'event_stream':
            return <AccountEventStreamToggle accountId={accountId} externalId={externalId} />
    }
}
