import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { fullName } from 'lib/utils'

import { OrganizationMemberType } from '~/types'

import { guestsTabLogic } from './guestsTabLogic'

function PromoteGuestModal({
    member,
    onClose,
    onConfirm,
}: {
    member: OrganizationMemberType
    onClose: () => void
    onConfirm: () => void
}): JSX.Element {
    const grantCount = (member as any).guest_grant_count ?? null
    const grantsCopy =
        grantCount === null
            ? null
            : grantCount === 1
              ? 'This will revoke their 1 resource grant.'
              : `This will revoke all ${grantCount} resource grants.`
    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={`Promote ${fullName(member.user)} to member?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" status="danger" onClick={onConfirm}>
                        Promote to member
                    </LemonButton>
                </>
            }
        >
            <LemonBanner type="warning">
                Promoting this guest resets their access controls — you will need to set up regular access from scratch.
                {grantsCopy ? <span className="block mt-1 font-medium">{grantsCopy}</span> : null}
            </LemonBanner>
        </LemonModal>
    )
}

export function GuestsTab(): JSX.Element {
    const { guests, guestsLoading } = useValues(guestsTabLogic)
    const { loadGuests, promoteGuest } = useActions(guestsTabLogic)

    const [memberToPromote, setMemberToPromote] = useState<OrganizationMemberType | null>(null)

    useOnMountEffect(loadGuests)

    const columns: LemonTableColumns<OrganizationMemberType> = [
        {
            key: 'user_profile_picture',
            render: (_, member) => <ProfilePicture user={member.user} />,
            width: 32,
        },
        {
            title: 'Name',
            key: 'user_name',
            render: (_, member) => <span className="ph-no-capture">{fullName(member.user)}</span>,
            sorter: (a, b) => fullName(a.user).localeCompare(fullName(b.user)),
        },
        {
            title: 'Email',
            key: 'user_email',
            render: (_, member) => <span className="ph-no-capture">{member.user.email}</span>,
            sorter: (a, b) => a.user.email.localeCompare(b.user.email),
        },
        {
            title: 'Joined',
            dataIndex: 'joined_at',
            key: 'joined_at',
            render: (joinedAt) => (
                <div className="whitespace-nowrap">
                    <TZLabel time={joinedAt as string} />
                </div>
            ),
            sorter: (a, b) => a.joined_at.localeCompare(b.joined_at),
        },
        {
            key: 'actions',
            width: 0,
            render: (_, member) => (
                <More
                    overlay={
                        <LemonButton fullWidth onClick={() => setMemberToPromote(member)} data-attr="promote-guest">
                            Promote to member
                        </LemonButton>
                    }
                />
            ),
        },
    ]

    return (
        <>
            <LemonTable
                dataSource={guests}
                columns={columns}
                rowKey="id"
                loading={guestsLoading}
                data-attr="org-guests-table"
                emptyState="No guests found"
                pagination={{ pageSize: 50 }}
            />

            {memberToPromote && (
                <PromoteGuestModal
                    member={memberToPromote}
                    onClose={() => setMemberToPromote(null)}
                    onConfirm={() => {
                        promoteGuest(memberToPromote.user.uuid)
                        setMemberToPromote(null)
                    }}
                />
            )}
        </>
    )
}
