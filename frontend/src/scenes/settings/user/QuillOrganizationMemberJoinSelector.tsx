import { OrganizationBasicType } from '~/types'

import { lockedDisabledReason } from '../shared/notificationLocks'
import { MEMBER_JOIN_HINT } from './emailPreferencesCopy'
import { QuillNotificationCheckbox } from './QuillNotificationCheckbox'
import { QuillNotificationSelector } from './QuillNotificationSelector'

export function QuillOrganizationMemberJoinSelector({
    organizations,
    expanded,
    onExpandedChange,
    enforcedFor,
    isOrgChecked,
    userLoading,
    onToggleOrganization,
    onEnableAll,
    onDisableAll,
    bulkDisabledReason,
}: {
    organizations: OrganizationBasicType[]
    expanded: boolean
    onExpandedChange: (expanded: boolean) => void
    enforcedFor: (orgId: string) => boolean | null
    isOrgChecked: (orgId: string, enforced: boolean | null) => boolean
    userLoading: boolean
    onToggleOrganization: (orgId: string, enabled: boolean) => void
    onEnableAll: () => void
    onDisableAll: () => void
    bulkDisabledReason?: string
}): JSX.Element {
    return (
        <QuillNotificationSelector
            title={`Select organizations (${organizations.length} available)`}
            expanded={expanded}
            onExpandedChange={onExpandedChange}
            hint={MEMBER_JOIN_HINT}
            bulkActions={{
                enableLabel: 'Enable for all organizations',
                disableLabel: 'Disable for all organizations',
                onEnableAll,
                onDisableAll,
                disabledReason: bulkDisabledReason,
            }}
        >
            {organizations.map((org) => {
                const enforced = enforcedFor(org.id)

                return (
                    <QuillNotificationCheckbox
                        key={`member-join-org-${org.id}`}
                        id={`member-join-org-${org.id}`}
                        dataAttr={`member_join_email_org_${org.id}`}
                        label={org.name}
                        lockedByAdmin={enforced !== null}
                        checked={isOrgChecked(org.id, enforced)}
                        onCheckedChange={(checked) => onToggleOrganization(org.id, checked)}
                        disabledReason={lockedDisabledReason(enforced, userLoading)}
                    />
                )
            })}
        </QuillNotificationSelector>
    )
}
