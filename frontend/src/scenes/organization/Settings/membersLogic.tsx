import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import type { membersLogicType } from './membersLogicType'
import { OrganizationMembershipLevel } from 'lib/constants'
import { OrganizationMemberType } from '~/types'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { membershipLevelToName } from '../../../lib/utils/permissioning'
import { lemonToast } from 'lib/components/lemonToast'

export const membersLogic = kea<membersLogicType>({
    path: ['scenes', 'organization', 'Settings', 'membersLogic'],
    connect: {
        values: [userLogic, ['user']],
    },
    actions: {
        changeMemberAccessLevel: (member: OrganizationMemberType, level: OrganizationMembershipLevel) => ({
            member,
            level,
        }),
        postRemoveMember: (userUuid: string) => ({ userUuid }),
    },
    loaders: ({ values, actions }) => ({
        members: {
            __default: [] as OrganizationMemberType[],
            loadMembers: async () => {
                return (await api.get('api/organizations/@current/members/?limit=200')).results
            },
            removeMember: async (member: OrganizationMemberType) => {
                await api.delete(`api/organizations/@current/members/${member.user.uuid}/`)
                lemonToast.success(
                    <>
                        Removed <b>{member.user.first_name}</b> from organization
                    </>
                )
                actions.postRemoveMember(member.user.uuid)
                return values.members.filter((thisMember) => thisMember.user.id !== member.user.id)
            },
        },
    }),
    selectors: {
        meFirstMembers: [
            (s) => [s.members, s.user],
            (members, user) => {
                const me = user && members.find((member) => member.user.uuid === user.uuid)
                const result: OrganizationMemberType[] = me ? [me] : []
                for (const member of members) {
                    if (!user || member.user.uuid !== user.uuid) {
                        result.push(member)
                    }
                }
                return result
            },
        ],
    },
    listeners: ({ actions }) => ({
        changeMemberAccessLevel: async ({ member, level }) => {
            await api.update(`api/organizations/@current/members/${member.user.uuid}/`, { level })
            lemonToast.success(
                <>
                    Made <b>{member.user.first_name}</b> organization {membershipLevelToName.get(level)}
                </>
            )
            // reload organization to account for no longer being organization owner
            if (level === OrganizationMembershipLevel.Owner) {
                organizationLogic.actions.loadCurrentOrganization()
            }
            actions.loadMembers()
        },
        postRemoveMember: async ({ userUuid }) => {
            if (userUuid === userLogic.values.user?.uuid) {
                location.reload()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadMembers,
    }),
})
