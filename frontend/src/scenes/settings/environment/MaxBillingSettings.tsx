import { LemonButton, LemonInputSelect, LemonTable, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { usersLemonSelectOptions } from 'lib/components/UserSelectItem'
import { fullName } from 'lib/utils'
import { useMemo, useState } from 'react'
import { userLogic } from 'scenes/userLogic'

import { OrganizationMemberType } from '~/types'

import { maxBillingSettingsLogic } from './maxBillingSettingsLogic'

export function MaxBillingSettings(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { membersWithSeats, sortedMembers, canEditSeats } = useValues(maxBillingSettingsLogic)
    const { addSeatsForMembers, removeSeat } = useActions(maxBillingSettingsLogic)
    const [membersToAdd, setMembersToAdd] = useState<string[]>([])

    const onSubmit = membersToAdd.length
        ? () => {
              addSeatsForMembers(membersToAdd)
              setMembersToAdd([])
          }
        : undefined

    const membersWithoutSeats = useMemo(() => {
        const membersInRole = new Set(membersWithSeats.map((member: OrganizationMemberType) => member.user.uuid))
        return sortedMembers?.filter((member) => !membersInRole.has(member.user.uuid)) ?? []
    }, [membersWithSeats, sortedMembers])

    return (
        <div className="my-2 pr-2 deprecated-space-y-2">
            <div className="flex items-center gap-2 justify-between min-h-10">
                <div className="flex items-center gap-2">
                    <div className="min-w-[16rem]">
                        <LemonInputSelect
                            placeholder="Search for members to add..."
                            value={membersToAdd}
                            onChange={(newValues: string[]) => setMembersToAdd(newValues)}
                            mode="multiple"
                            disabled={!canEditSeats}
                            options={usersLemonSelectOptions(
                                membersWithoutSeats.map((member) => member.user),
                                'uuid'
                            )}
                        />
                    </div>

                    <LemonButton
                        type="primary"
                        onClick={onSubmit}
                        disabledReason={
                            !canEditSeats
                                ? 'You cannot edit this'
                                : !onSubmit
                                ? 'Please select members to add'
                                : undefined
                        }
                    >
                        Add members
                    </LemonButton>
                </div>
            </div>

            <LemonTable
                columns={[
                    {
                        key: 'user_profile_picture',
                        render: function ProfilePictureRender(_, member) {
                            return <ProfilePicture user={member.user} />
                        },
                        width: 32,
                    },
                    {
                        title: 'Name',
                        key: 'user_name',
                        render: (_, member) =>
                            member.user.uuid === user?.uuid ? `${fullName(member.user)} (you)` : fullName(member.user),
                        sorter: (a, b) => fullName(a.user).localeCompare(fullName(b.user)),
                    },
                    {
                        title: 'Email',
                        key: 'user_email',
                        render: (_, member) => {
                            return <>{member.user.email}</>
                        },
                        sorter: (a, b) => a.user.email.localeCompare(b.user.email),
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, member) => {
                            return (
                                <div className="flex items-center gap-2">
                                    <LemonButton
                                        status="danger"
                                        size="small"
                                        type="tertiary"
                                        disabledReason={!canEditSeats ? 'You cannot edit this' : undefined}
                                        onClick={() => removeSeat(member.user.uuid)}
                                    >
                                        Remove
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
                dataSource={membersWithSeats}
            />
        </div>
    )
}
