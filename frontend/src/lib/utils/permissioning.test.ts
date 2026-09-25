import { OrganizationMembershipLevel } from 'lib/constants'
import { getReasonForAccessLevelChangeProhibition } from 'lib/utils/permissioning'

import { OrganizationMemberType, UserType } from '~/types'

const OWNER_UUID = 'owner-uuid'

const owner = { uuid: OWNER_UUID } as UserType

function memberSelf(level: OrganizationMembershipLevel): OrganizationMemberType {
    return { user: { uuid: OWNER_UUID }, level } as OrganizationMemberType
}

describe('getReasonForAccessLevelChangeProhibition', () => {
    it('lets an owner step down while another owner remains', () => {
        expect(
            getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Owner,
                owner,
                memberSelf(OrganizationMembershipLevel.Owner),
                OrganizationMembershipLevel.Admin,
                true
            )
        ).toBeNull()
    })

    it('blocks the only owner from stepping down', () => {
        expect(
            getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Owner,
                owner,
                memberSelf(OrganizationMembershipLevel.Owner),
                OrganizationMembershipLevel.Admin,
                false
            )
        ).toEqual(
            "You can't lower your own access level as the organization's only owner. Make someone else an owner first."
        )
    })

    it('blocks an admin from changing their own level', () => {
        expect(
            getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                owner,
                memberSelf(OrganizationMembershipLevel.Admin),
                OrganizationMembershipLevel.Member,
                true
            )
        ).toEqual("You can't change your own access level.")
    })
})
