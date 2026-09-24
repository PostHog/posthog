import { OrganizationMembershipLevel } from 'lib/constants'
import { getMemberRemovalOption } from 'lib/utils/permissioning'

import { OrganizationMemberType, UserType } from '~/types'

const ONLY_OWNER_REASON = "You can't leave the organization as its only owner. Make someone else an owner first."

function member(uuid: string, level: OrganizationMembershipLevel): OrganizationMemberType {
    return { user: { uuid }, level } as OrganizationMemberType
}

describe('permissioning', () => {
    const me = { uuid: 'me' } as UserType
    const meAsOwner = member('me', OrganizationMembershipLevel.Owner)
    const otherOwner = member('other', OrganizationMembershipLevel.Owner)
    const otherAdmin = member('other', OrganizationMembershipLevel.Admin)

    test.each([
        [
            'an owner can remove another owner',
            OrganizationMembershipLevel.Owner,
            otherOwner,
            [meAsOwner, otherOwner],
            { shown: true },
        ],
        [
            'an admin cannot remove an owner',
            OrganizationMembershipLevel.Admin,
            otherOwner,
            [otherOwner],
            { shown: false },
        ],
        ['an admin can remove an admin', OrganizationMembershipLevel.Admin, otherAdmin, [otherAdmin], { shown: true }],
        [
            'a member cannot remove an admin',
            OrganizationMembershipLevel.Member,
            otherAdmin,
            [otherAdmin],
            { shown: false },
        ],
        [
            'the only owner cannot leave',
            OrganizationMembershipLevel.Owner,
            meAsOwner,
            [meAsOwner],
            { shown: true, disabledReason: ONLY_OWNER_REASON },
        ],
        [
            'an owner can leave once a second owner exists',
            OrganizationMembershipLevel.Owner,
            meAsOwner,
            [meAsOwner, otherOwner],
            { shown: true },
        ],
    ])('%s', (_, myLevel, target, allMembers, expected) => {
        expect(getMemberRemovalOption(myLevel, me, target, allMembers)).toEqual(expected)
    })
})
