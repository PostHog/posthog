import {
    ActivityLogItem,
    ActivityLogUserName,
    Description,
    HumanizedChange,
    activityLogSummary,
    defaultDescriber,
} from 'lib/components/ActivityLog/humanizeActivity'
import { SentenceList } from 'lib/components/ActivityLog/SentenceList'
import { UserNameWithEmail } from 'lib/components/ActivityLog/UserNameWithEmail'
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
            summary: activityLogSummary(
                logItem,
                'Created the organization',
                nameOrLinkToOrganization(logItem.detail.name)
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> created the organization{' '}
                    <strong>{nameOrLinkToOrganization(logItem?.detail.name)}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        const organizationName = logItem.detail.name || 'Organization'
        return {
            summary: activityLogSummary(logItem, 'Deleted the organization', organizationName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted the organization{' '}
                    <strong>{organizationName}</strong>
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
                summary: activityLogSummary(logItem, changeDescription, nameOrLinkToOrganization(logItem.detail.name)),
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> {changeDescription} for organization{' '}
                        {nameOrLinkToOrganization(logItem?.detail.name)}
                    </>
                ),
            }
        } else if (changes.length > 1) {
            return {
                summary: activityLogSummary(
                    logItem,
                    <>Updated {changes.length} organization settings</>,
                    nameOrLinkToOrganization(logItem.detail.name)
                ),
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> updated <strong>{changes.length} settings</strong> for
                        organization {nameOrLinkToOrganization(logItem?.detail.name)}
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
            summary: activityLogSummary(
                logItem,
                'Added an organization member',
                <>
                    <UserNameWithEmail name={userName} email={userEmail} /> in{' '}
                    {nameOrLinkToOrganization(organizationName)}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> added user{' '}
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
            summary: activityLogSummary(
                logItem,
                'Removed an organization member',
                <>
                    <UserNameWithEmail name={userName} email={userEmail} /> in{' '}
                    {nameOrLinkToOrganization(organizationName)}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> removed user{' '}
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
                summary: activityLogSummary(
                    logItem,
                    <>
                        Changed role from {String(beforeLevel)} to {String(afterLevel)}
                    </>,
                    <>
                        <UserNameWithEmail name={userName} email={userEmail} /> in{' '}
                        {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
                description: (
                    <>
                        <ActivityLogUserName logItem={logItem} /> changed{' '}
                        <strong>
                            {userName} ({userEmail})
                        </strong>
                        's role from <strong>{String(beforeLevel)}</strong> to <strong>{String(afterLevel)}</strong> in
                        organization {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
            }
        }

        return {
            summary: activityLogSummary(
                logItem,
                'Updated organization membership',
                <>
                    <UserNameWithEmail name={userName} email={userEmail} /> in{' '}
                    {nameOrLinkToOrganization(organizationName)}
                </>
            ),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> updated{' '}
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
    // The context names whoever created the invite, who is not always the person who acted on this
    // row, so the email must come from the same context as the name. A system or impersonated row
    // hides it, as the actor's name and avatar do.
    const inviterEmail = logItem.is_system || logItem.was_impersonated ? undefined : context?.inviter_user_email
    const inviter = context?.inviter_user_name ? (
        <UserNameWithEmail name={context.inviter_user_name} email={inviterEmail} />
    ) : (
        <ActivityLogUserName logItem={logItem} />
    )

    if (logItem.activity == 'created') {
        return {
            summary: activityLogSummary(
                logItem,
                <>Sent an invitation to join as {level}</>,
                <>
                    {targetEmail} in {nameOrLinkToOrganization(organizationName)}
                </>,
                undefined,
                inviter
            ),
            description: (
                <>
                    {inviter} sent an invitation to <strong>{targetEmail}</strong> to join organization{' '}
                    {nameOrLinkToOrganization(organizationName)} as <strong>{level}</strong>
                </>
            ),
        }
    }

    if (logItem.activity == 'deleted') {
        return {
            summary: activityLogSummary(
                logItem,
                'Revoked the invitation',
                <>
                    {targetEmail} in {nameOrLinkToOrganization(organizationName)}
                </>,
                undefined,
                inviter
            ),
            description: (
                <>
                    {inviter} revoked the invitation for <strong>{targetEmail}</strong> to join organization{' '}
                    {nameOrLinkToOrganization(organizationName)}
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
                summary: activityLogSummary(
                    logItem,
                    <>{changeDescription} for the invitation</>,
                    <>
                        {targetEmail} in {nameOrLinkToOrganization(organizationName)}
                    </>,
                    undefined,
                    inviter
                ),
                description: (
                    <>
                        {inviter} {changeDescription} for the invitation sent to <strong>{targetEmail}</strong> to join
                        organization {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
            }
        } else if (changes.length > 1) {
            return {
                summary: activityLogSummary(
                    logItem,
                    <>Updated {changes.length} invitation settings</>,
                    <>
                        {targetEmail} in {nameOrLinkToOrganization(organizationName)}
                    </>,
                    undefined,
                    inviter
                ),
                description: (
                    <>
                        {inviter} updated <strong>{changes.length} settings</strong> for the invitation sent to{' '}
                        <strong>{targetEmail}</strong> to join organization {nameOrLinkToOrganization(organizationName)}
                    </>
                ),
            }
        }
    }

    return defaultDescriber(logItem, asNotification)
}

function describeOrganizationDomainUpdate(logItem: ActivityLogItem, domainName: string): HumanizedChange | null {
    const changes = logItem.detail.changes || []
    const hasScimEnabledChange = changes.some((c) => c.field === 'SCIM provisioning')

    const descriptions: JSX.Element[] = []
    const summaryChanges: Description[] = []
    for (const change of changes) {
        if (change.field === 'SCIM provisioning') {
            summaryChanges.push(change.after ? 'Enabled SCIM provisioning' : 'Disabled SCIM provisioning')
            descriptions.push(
                <>
                    {change.after ? 'enabled' : 'disabled'} <strong>SCIM provisioning</strong> for domain{' '}
                    <strong>{domainName}</strong>
                </>
            )
        } else if (change.field === 'scim_bearer_token') {
            if (!hasScimEnabledChange) {
                summaryChanges.push('Rotated the SCIM bearer token')
                descriptions.push(
                    <>
                        rotated the <strong>SCIM bearer token</strong> for domain <strong>{domainName}</strong>
                    </>
                )
            }
        } else {
            summaryChanges.push(<>Updated {change.field}</>)
            descriptions.push(
                <>
                    updated <strong>{change.field}</strong> for domain <strong>{domainName}</strong>
                </>
            )
        }
    }

    if (descriptions.length > 0) {
        return {
            summary: activityLogSummary(logItem, <SentenceList listParts={summaryChanges} />, domainName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} />{' '}
                    {descriptions.length === 1 ? (
                        descriptions[0]
                    ) : (
                        <ul>
                            {descriptions.map((d, i) => (
                                <li key={i}>{d}</li>
                            ))}
                        </ul>
                    )}
                </>
            ),
        }
    }
    return null
}

export function organizationDomainActivityDescriber(
    logItem: ActivityLogItem,
    asNotification?: boolean
): HumanizedChange {
    const context = logItem.detail.context
    const domainName = context?.domain || 'unknown domain'

    if (logItem.activity === 'updated') {
        const result = describeOrganizationDomainUpdate(logItem, domainName)
        if (result) {
            return result
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            summary: activityLogSummary(logItem, 'Deleted the domain', domainName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted domain <strong>{domainName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'created') {
        return {
            summary: activityLogSummary(logItem, 'Added the domain', domainName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> added domain <strong>{domainName}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, domainName)
}

export function legalDocumentActivityDescriber(logItem: ActivityLogItem, asNotification?: boolean): HumanizedChange {
    const detail = logItem.detail as {
        name?: string | null
        context?: { document_type?: string; company_name?: string }
    }
    const documentType = detail.context?.document_type || 'document'
    const companyName = detail.context?.company_name || detail.name || 'company'
    const article = documentType === 'BAA' || documentType === 'DPA' ? 'a' : 'the'

    if (logItem.activity === 'created') {
        return {
            summary: activityLogSummary(logItem, `Generated ${article} ${documentType}`, companyName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> generated {article} <strong>{documentType}</strong> for{' '}
                    <strong>{companyName}</strong>
                </>
            ),
        }
    }

    if (logItem.activity === 'deleted') {
        return {
            summary: activityLogSummary(logItem, `Deleted ${article} ${documentType}`, companyName),
            description: (
                <>
                    <ActivityLogUserName logItem={logItem} /> deleted {article} <strong>{documentType}</strong> for{' '}
                    <strong>{companyName}</strong>
                </>
            ),
        }
    }

    return defaultDescriber(logItem, asNotification, `${documentType} for ${companyName}`)
}
