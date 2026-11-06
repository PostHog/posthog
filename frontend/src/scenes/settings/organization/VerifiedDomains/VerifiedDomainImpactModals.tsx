import { useActions, useValues } from 'kea'

import { CountedPaginatedResponse } from 'lib/api'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

import { verifiedDomainImpactLogic } from './verifiedDomainImpactLogic'

function impactedMemberColumns(currentUserUuid?: string): LemonTableColumns<OrganizationMemberType> {
    return [
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
                        <div>
                            {member.user.uuid === currentUserUuid
                                ? `${fullName(member.user)} (you)`
                                : fullName(member.user)}
                        </div>
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
}

function ImpactedMembersTable({
    impact,
    loading,
}: {
    impact: CountedPaginatedResponse<OrganizationMemberType> | null
    loading: boolean
}): JSX.Element {
    const { user } = useValues(userLogic)
    const members = impact?.results ?? []
    const count = impact?.count ?? members.length
    return (
        <>
            <LemonTable
                dataSource={members}
                columns={impactedMemberColumns(user?.uuid)}
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
                    <LemonButton
                        status="danger"
                        type="primary"
                        onClick={confirmRemoveDomain}
                        loading={domainImpactLoading}
                    >
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
                            Logins are restricted to verified email domains. Removing this domain means{' '}
                            {impactedCount === 1 ? 'this member' : `these ${impactedCount} members`} can no longer log
                            in:
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
            </div>
        </LemonModal>
    )
}
