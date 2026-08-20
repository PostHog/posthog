import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonTable, Spinner } from '@posthog/lemon-ui'

import { accessControlsLogic } from './accessControlsLogic'
import { MemberProfileCell } from './MemberProfileCell'
import { AccessControlMemberEntry } from './types'

export function PrivateProjectConfirmModal({ projectId }: { projectId: string }): JSX.Element {
    const logic = accessControlsLogic({ projectId })
    const { privateProjectConfirmOpen, membersLosingProjectAccess, membersDataLoading } = useValues(logic)
    const { closePrivateProjectConfirm, confirmPrivateProject } = useActions(logic)

    const losingCount = membersLosingProjectAccess.length
    const hasMembersLosingAccess = losingCount > 0

    return (
        <LemonModal
            isOpen={privateProjectConfirmOpen}
            onClose={closePrivateProjectConfirm}
            title="Set default to no access"
            width={640}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closePrivateProjectConfirm}>
                        Cancel
                    </LemonButton>
                    {hasMembersLosingAccess && (
                        <LemonButton type="secondary" status="danger" onClick={() => confirmPrivateProject(false)}>
                            Remove their access
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        disabledReason={membersDataLoading ? 'Loading members' : undefined}
                        onClick={() => confirmPrivateProject(hasMembersLosingAccess)}
                    >
                        {hasMembersLosingAccess ? 'Keep them and continue' : 'Set to no access'}
                    </LemonButton>
                </>
            }
        >
            {membersDataLoading ? (
                <div className="flex items-center gap-2 py-4">
                    <Spinner />
                    <span>Checking who reaches this project through the default…</span>
                </div>
            ) : losingCount === 0 ? (
                <p className="mb-0">
                    No members reach this project only through the default. Setting it to no access removes no one.
                </p>
            ) : (
                <div className="space-y-3">
                    <LemonBanner type="warning">
                        {losingCount === 1 ? '1 member reaches' : `${losingCount} members reach`} this project only
                        through the default. No access removes them unless you keep them as explicit members first.
                    </LemonBanner>
                    <LemonTable
                        dataSource={membersLosingProjectAccess}
                        rowKey="organization_membership_id"
                        columns={[
                            {
                                title: 'Member',
                                key: 'member',
                                render: function RenderMember(_, member: AccessControlMemberEntry) {
                                    return <MemberProfileCell user={member.user} />
                                },
                            },
                        ]}
                    />
                </div>
            )}
        </LemonModal>
    )
}
