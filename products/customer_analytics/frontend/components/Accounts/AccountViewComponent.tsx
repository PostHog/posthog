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
import type { AccountViewTileConfig } from './accountViewTileConfig'

interface AccountViewComponentProps {
    kind: AccountViewComponentKind
    accountId: string
    externalId: string
    instanceId?: string
    initialConfig?: AccountViewTileConfig
    onConfigChange?: (config: AccountViewTileConfig) => void
    embedded?: boolean
}

export function AccountViewComponent({
    kind,
    accountId,
    externalId,
    instanceId,
    initialConfig,
    onConfigChange,
    embedded = true,
}: AccountViewComponentProps): JSX.Element {
    const tileProps = { instanceId, initialConfig, onConfigChange }
    switch (kind) {
        case 'notes':
            return <AccountNotesExpansion accountId={accountId} embedded={embedded} {...tileProps} />
        case 'tasks':
            return (
                <CustomerTasksTabContent
                    accountId={accountId}
                    canCreate={userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Editor)}
                    canViewAll={userHasAccess(AccessControlResourceType.CustomerAnalytics, AccessControlLevel.Viewer)}
                    embedded={embedded}
                    {...tileProps}
                />
            )
        case 'users':
            return <AccountRelatedUsersExpansion externalId={externalId} embedded={embedded} {...tileProps} />
        case 'relationships':
            return <AccountRelationshipsExpansion accountId={accountId} embedded={embedded} {...tileProps} />
        case 'feature_requests':
            return <AccountFeatureRequestsExpansion accountId={accountId} embedded={embedded} {...tileProps} />
        case 'usage':
            return <AccountBillingExpansion accountId={accountId} externalId={externalId} kind="usage" {...tileProps} />
        case 'spend':
            return <AccountBillingExpansion accountId={accountId} externalId={externalId} kind="spend" {...tileProps} />
        case 'opportunities':
            return <AccountOpportunitiesExpansion accountId={accountId} embedded={embedded} instanceId={instanceId} />
        case 'conversations':
            return <AccountConversationsExpansion accountId={accountId} embedded={embedded} {...tileProps} />
        case 'meetings':
            return <AccountMeetingsExpansion accountId={accountId} embedded={embedded} {...tileProps} />
        case 'event_stream':
            return <AccountEventStreamToggle accountId={accountId} externalId={externalId} />
    }
}
