import { actions, connect, kea, listeners, path, selectors } from 'kea'
import api from 'lib/api'
import { membersLogic } from 'scenes/organization/membersLogic'

import { roleAccessControlLogic } from '~/layout/navigation-3000/sidepanel/panels/access_control/roleAccessControlLogic'
import { AccessControlResponseType, OrganizationMemberSeatBasedProduct, OrganizationMemberType } from '~/types'

import type { maxBillingSettingsLogicType } from './maxBillingSettingsLogicType'

export const maxBillingSettingsLogic = kea<maxBillingSettingsLogicType>([
    path(['scenes', 'project', 'Settings', 'maxBillingSettingsLogic']),
    connect(() => ({
        values: [membersLogic, ['sortedMembers'], roleAccessControlLogic, ['resourceAccessControls']],
        actions: [membersLogic, ['ensureAllMembersLoaded', 'loadMemberUpdates']],
    })),
    actions({
        removeSeat: (memberId: string) => ({ memberId }),
        addSeatsForMembers: (memberIds: string[]) => ({ memberIds }),
    }),
    selectors({
        membersWithSeats: [
            (s) => [s.sortedMembers],
            (members: OrganizationMemberType[]) => {
                return (
                    members?.filter((member) =>
                        member.enabled_seat_based_products?.includes(OrganizationMemberSeatBasedProduct.MAX_AI)
                    ) ?? []
                )
            },
        ],
        canEditSeats: [
            (s) => [s.resourceAccessControls],
            (resourceAccessControls: AccessControlResponseType | null): boolean | null => {
                return resourceAccessControls?.user_can_edit_access_levels ?? null
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        addSeatsForMembers: async ({ memberIds }) => {
            const membersToUpdate = values.sortedMembers?.filter((member) => memberIds.includes(member.user.uuid)) ?? []
            await Promise.all(
                membersToUpdate.map(
                    async (member: OrganizationMemberType) =>
                        await api.organizationMembers.update(member.user.uuid, {
                            enabled_seat_based_products: [
                                ...(member.enabled_seat_based_products ?? []),
                                OrganizationMemberSeatBasedProduct.MAX_AI,
                            ],
                        })
                )
            )
            actions.loadMemberUpdates()
        },
        removeSeat: async ({ memberId }) => {
            const member = values.sortedMembers?.find((member) => member.user.uuid === memberId)
            if (!member) {
                return
            }
            await api.organizationMembers.update(member.user.uuid, {
                enabled_seat_based_products: (member.enabled_seat_based_products ?? []).filter(
                    (product) => product !== OrganizationMemberSeatBasedProduct.MAX_AI
                ),
            })
            actions.loadMemberUpdates()
        },
    })),
])
