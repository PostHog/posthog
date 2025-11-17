import {
    ActivityLogItem,
    HumanizedChange,
    defaultDescriber,
    userNameForLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { urls } from 'scenes/urls'

const nameOrLinkToOrganization = (name?: string | null): string | JSX.Element => {
    let displayName = name || 'Organization'

    if (displayName.length > 32) {
        displayName = displayName.slice(0, 32) + '...'
    }

    return <Link to={urls.settings('organization')}>{displayName}</Link>
}

export function organizationActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    if (logItem.scope === 'OrganizationMembership') {
        return organizationMembershipActivityDescriber(logItem, asNotification)
    }
    if (logItem.scope === 'OrganizationInvite') {
        return organizationInviteActivityDescriber(logItem, asNotification)
    }
    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> created the organization{' '}
                    <strong>{nameOrLinkToOrganization(logItem?.detail.name)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> deleted the organization{' '}
                    <strong>{logItem.detail.name || 'Organization'}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes = logItem.detail.changes || []

        if (changes.length === 1) {
            const change = changes[0]
            const changeDescription = (
                <>
                    updated the <strong>{change.field}</strong>
                </>
            )

            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> {changeDescription} for
                        organization {nameOrLinkToOrganization(logItem?.detail.name)}
                    </>
                ),
            }
        } else if (changes.length > 1) {
            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated{' '}
                        <strong>{changes.length} settings</strong> for organization{' '}
                        {nameOrLinkToOrganization(logItem?.detail.name)}
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification, nameOrLinkToOrganization(logItem?.detail.name))
}

function organizationMembershipActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const context = logItem?.detail?.context
    const userEmail = context?.user_email || ''
    const userName = context?.user_name || userEmail
    const organizationName = context?.organization_name || 'the organization'

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> added user{' '}
                    <strong>
                        {userName} ({userEmail})
                    </strong>{' '}
                    to organization{nameOrLinkToOrganization(organizationName)}
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> removed user{' '}
                    <strong>
                        {userName} ({userEmail})
                    </strong>{' '}
                    from organization {nameOrLinkToOrganization(organizationName)}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes = logItem.detail.changes || []
        const levelChange = changes.find((c) => c.field === 'level')

        if (levelChange) {
            const beforeLevel =
                membershipLevelToName.get(levelChange.before as OrganizationMembershipLevel) || levelChange.before
            const afterLevel =
                membershipLevelToName.get(levelChange.after as OrganizationMembershipLevel) || levelChange.after

            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> changed{' '}
                        <strong>
                            {userName} ({userEmail})
                        </strong>
                        's role from <strong>{beforeLevel}</strong> to <strong>{afterLevel}</strong> in organization{' '}
                        {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
            }
        }

        return {
            description: (
                <>
                    <strong className="ph-no-capture">{userNameForLogItem(logItem)}</strong> updated{' '}
                    <strong>
                        {userName} ({userEmail})
                    </strong>
                    's membership in organization {nameOrLinkToOrganization(organizationName)}
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification)
}

function organizationInviteActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const context = logItem?.detail?.context
    const targetEmail = context?.target_email || ''
    const organizationName = context?.organization_name || 'the organization'
    const level = context?.level || 'member'
    const inviterName = context?.inviter_user_name || userNameForLogItem(logItem) || 'System'

    if (logItem.activity == 'created') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{inviterName}</strong> sent an invitation to{' '}
                    <strong>{targetEmail}</strong> to join organization {nameOrLinkToOrganization(organizationName)} as{' '}
                    <strong>{level}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            description: (
                <>
                    <strong className="ph-no-capture">{inviterName}</strong> revoked the invitation for{' '}
                    <strong>{targetEmail}</strong> to join organization {nameOrLinkToOrganization(organizationName)}
                </>
            ),
        }
    }

    if (logItem.activity == 'updated') {
        const changes = logItem.detail.changes || []

        if (changes.length === 1) {
            const change = changes[0]
            const changeDescription = (
                <>
                    updated <strong>{change.field}</strong>
                </>
            )

            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{inviterName}</strong> {changeDescription} for the invitation
                        sent to <strong>{targetEmail}</strong> to join organization{' '}
                        {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
            }
        } else if (changes.length > 1) {
            return {
                description: (
                    <>
                        <strong className="ph-no-capture">{inviterName}</strong> updated{' '}
                        <strong>{changes.length} settings</strong> for the invitation sent to{' '}
                        <strong>{targetEmail}</strong> to join organization {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification)
}
