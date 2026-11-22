import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Text,
} from '@posthog/quill'

import { CountedPaginatedResponse } from 'lib/api'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

import { QuillImpactedMembersTable } from './QuillImpactedMembersTable'
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const impactedCount = domainImpact?.count ?? 0
    const showImpact =
        !!currentOrganization?.enforce_verified_domains &&
        !!removeDomainPrompt?.is_verified &&
        (domainImpactLoading || impactedCount > 0)
    const removeWarning = removeDomainPrompt?.is_verified
        ? 'This cannot be undone. If you have SAML configured or SSO enforced, it will be immediately disabled.'
        : 'This cannot be undone.'

    if (todayRailNav) {
        return (
            <AlertDialog open={!!removeDomainPrompt} onOpenChange={(open) => !open && closeRemoveDomainPrompt()}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>{`Remove ${removeDomainPrompt?.domain ?? 'domain'}?`}</AlertDialogTitle>
                        <AlertDialogDescription>{removeWarning}</AlertDialogDescription>
                    </AlertDialogHeader>
                    {showImpact && (
                        <div className="flex flex-col gap-2">
                            <Text size="xs" render={<p className="m-0" />}>
                                {`Logins are restricted to verified email domains. Removing this domain means ${
                                    impactedCount === 1 ? 'this member' : `these ${impactedCount} members`
                                } can no longer log in:`}
                            </Text>
                            <QuillImpactedMembersTable impact={domainImpact} loading={domainImpactLoading} />
                        </div>
                    )}
                    <AlertDialogFooter>
                        <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                        <Button
                            variant="destructive-outline"
                            onClick={confirmRemoveDomain}
                            loading={domainImpactLoading}
                        >
                            Remove domain
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        )
    }

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
                <p>{removeWarning}</p>
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const impactedCount = enforcementImpact?.count ?? 0

    if (todayRailNav) {
        return (
            <AlertDialog open={enforcementPromptOpen} onOpenChange={(open) => !open && closeEnforcementPrompt()}>
                <AlertDialogContent>
                    <AlertDialogHeader>
                        <AlertDialogTitle>Restrict logins to verified email domains?</AlertDialogTitle>
                        <AlertDialogDescription>
                            {`${impactedCount === 1 ? '1 member has' : `${impactedCount} members have`} an email address outside your verified domains and will no longer be able to log in. Confirming also removes them from this organization.`}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <QuillImpactedMembersTable impact={enforcementImpact} loading={enforcementImpactLoading} />
                    <AlertDialogFooter>
                        <Button
                            variant="outline"
                            onClick={closeEnforcementPrompt}
                            disabledReason={enforcementRemovalLoading ? 'Removing members...' : undefined}
                        >
                            Cancel
                        </Button>
                        <Button
                            variant="destructive-outline"
                            onClick={confirmEnforceVerifiedDomains}
                            loading={enforcementRemovalLoading}
                        >
                            {impactedCount === 1
                                ? 'Remove 1 member and restrict'
                                : `Remove ${impactedCount} members and restrict`}
                        </Button>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        )
    }

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
