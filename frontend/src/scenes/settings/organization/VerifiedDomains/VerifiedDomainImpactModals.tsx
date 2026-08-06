import { useActions, useValues } from 'kea'

import { CountedPaginatedResponse } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { fullName } from 'lib/utils/strings'

import { OrganizationMemberType } from '~/types'

import { verifiedDomainImpactLogic } from './verifiedDomainImpactLogic'

const columns: LemonTableColumns<OrganizationMemberType> = [
    {
        key: 'user_profile_picture',
        width: 32,
        render: function ProfilePictureRender(_, member) {
            return <ProfilePicture user={member.user} />
        },
    },
    {
        key: 'user',
        title: 'Name',
        render: function NameRender(_, member) {
            return (
                <div className="ph-no-capture">
                    <div>{fullName(member.user)}</div>
                    <div className="text-secondary">{member.user.email}</div>
                </div>
            )
        },
    },
    {
        key: 'level',
        title: 'Level',
        render: function LevelRender(_, member) {
            return membershipLevelToName.get(member.level) ?? `unknown (${member.level})`
        },
    },
]

function ImpactedMembersTable({
    impact,
    loading,
}: {
    impact: CountedPaginatedResponse<OrganizationMemberType> | null
    loading: boolean
}): JSX.Element {
    const members = impact?.results ?? []
    const count = impact?.count ?? members.length
    return (
        <>
            <LemonTable
                dataSource={members}
                columns={columns}
                loading={loading}
                rowKey="id"
                size="small"
                pagination={{ pageSize: 8, hideOnSinglePage: true }}
                embedded
            />
            {count > members.length && (
                <div className="text-secondary text-xs mt-1">
                    Showing {members.length} of {count} members.
                </div>
            )}
        </>
    )
}

export function RemoveDomainModal(): JSX.Element {
    const { removeDomainPrompt, domainImpact, domainImpactLoading, currentOrganization } =
        useValues(verifiedDomainImpactLogic)
    const { closeRemoveDomainPrompt, confirmRemoveDomain } = useActions(verifiedDomainImpactLogic)

    const impactedCount = domainImpact?.count ?? 0
    const showImpact =
        !!currentOrganization?.enforce_verified_domains &&
        !!removeDomainPrompt?.is_verified &&
        (domainImpactLoading || impactedCount > 0)

    return (
        <LemonModal
            title={`Remove ${removeDomainPrompt?.domain ?? 'domain'}?`}
            isOpen={!!removeDomainPrompt}
            onClose={closeRemoveDomainPrompt}
            width={showImpact ? 600 : undefined}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeRemoveDomainPrompt}>
                        Cancel
                    </LemonButton>
                    <LemonButton status="danger" type="primary" onClick={confirmRemoveDomain}>
                        Remove domain
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <p>
                    {removeDomainPrompt?.is_verified
                        ? 'This cannot be undone. If you have SAML configured or SSO enforced, it will be immediately disabled.'
                        : 'This cannot be undone.'}
                </p>
                {showImpact && (
                    <>
                        <p>
                            Membership is restricted to verified email domains, and this domain admits{' '}
                            {impactedCount === 1 ? '1 member' : `${impactedCount} members`}. If no other verified domain
                            covers their email, they will lose access:
                        </p>
                        <ImpactedMembersTable impact={domainImpact} loading={domainImpactLoading} />
                    </>
                )}
            </div>
        </LemonModal>
    )
}

export function EnforceVerifiedDomainsModal(): JSX.Element {
    const { enforcementPromptOpen, enforcementImpact, enforcementImpactLoading, enforcementRemovalLoading } =
        useValues(verifiedDomainImpactLogic)
    const { closeEnforcementPrompt, confirmEnforceVerifiedDomains } = useActions(verifiedDomainImpactLogic)

    const impactedCount = enforcementImpact?.count ?? 0
    const includesOwner = (enforcementImpact?.results ?? []).some(
        (member) => member.level === OrganizationMembershipLevel.Owner
    )

    return (
        <LemonModal
            title="Restrict logins to verified email domains?"
            isOpen={enforcementPromptOpen}
            onClose={closeEnforcementPrompt}
            width={600}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeEnforcementPrompt}
                        disabledReason={enforcementRemovalLoading ? 'Removing members...' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        status="danger"
                        type="primary"
                        onClick={confirmEnforceVerifiedDomains}
                        loading={enforcementRemovalLoading}
                    >
                        {impactedCount === 1
                            ? 'Remove 1 member and restrict'
                            : `Remove ${impactedCount} members and restrict`}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-2">
                <p>
                    {impactedCount === 1 ? '1 member has' : `${impactedCount} members have`} an email address outside
                    your verified domains and will no longer be able to log in. Confirming also removes them from this
                    organization.
                </p>
                <ImpactedMembersTable impact={enforcementImpact} loading={enforcementImpactLoading} />
                {includesOwner && (
                    <p className="text-secondary text-xs">
                        Organization owners are never removed, but they lose access until the restriction is turned off.
                    </p>
                )}
            </div>
        </LemonModal>
    )
}
