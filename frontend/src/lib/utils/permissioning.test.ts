import { OrganizationMembershipLevel } from 'lib/constants'

import { OrganizationMemberType, UserType } from '~/types'

import { getReasonForAccessLevelChangeProhibition } from './permissioning'

function makeMember(overrides: Partial<OrganizationMemberType> & { uuid?: string } = {}): OrganizationMemberType {
    const { uuid = 'member-uuid', ...rest } = overrides
    return {
        id: '1',
        user: {
            uuid,
            email: 'member@example.com',
            first_name: 'Member',
        } as OrganizationMemberType['user'],
        level: OrganizationMembershipLevel.Member,
        joined_at: '2024-01-01',
        updated_at: '2024-01-01',
        is_2fa_enabled: false,
        has_social_auth: false,
        last_login: null,
        ...rest,
    } as OrganizationMemberType
}

const currentUser = { uuid: 'current-user-uuid' } as UserType

describe('getReasonForAccessLevelChangeProhibition', () => {
    describe('ownerless organization rescue', () => {
        it('allows admin to promote another member to owner when org has no owner', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                currentUser,
                makeMember(),
                OrganizationMembershipLevel.Owner,
                false // no owner
            )
            expect(result).toBeNull()
        })

        it('allows admin to self-promote to owner when org has no owner', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                currentUser,
                makeMember({ uuid: 'current-user-uuid' }),
                OrganizationMembershipLevel.Owner,
                false
            )
            expect(result).toBeNull()
        })

        it('blocks admin from promoting to owner when org has an owner', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                currentUser,
                makeMember(),
                OrganizationMembershipLevel.Owner,
                true
            )
            expect(result).not.toBeNull()
        })

        it('blocks regular member from promoting even when org has no owner', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Member,
                currentUser,
                makeMember(),
                OrganizationMembershipLevel.Owner,
                false
            )
            expect(result).not.toBeNull()
        })

        it('returns all levels as allowed for admin when org has no owner (array mode)', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                currentUser,
                makeMember({ uuid: 'current-user-uuid' }),
                [OrganizationMembershipLevel.Owner],
                false
            )
            expect(result).toBeNull()
        })
    })

    describe('standard behavior (org has owner)', () => {
        it('blocks self-level-change', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                currentUser,
                makeMember({ uuid: 'current-user-uuid' }),
                OrganizationMembershipLevel.Member,
                true
            )
            expect(result).toBe("You can't change your own access level.")
        })

        it('allows owner to change any member level', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Owner,
                currentUser,
                makeMember(),
                OrganizationMembershipLevel.Admin,
                true
            )
            expect(result).toBeNull()
        })

        it('blocks admin from promoting to level above their own', () => {
            const result = getReasonForAccessLevelChangeProhibition(
                OrganizationMembershipLevel.Admin,
                currentUser,
                makeMember(),
                OrganizationMembershipLevel.Owner,
                true
            )
            expect(result).toBe('You can only change access level of others to lower or equal to your current one.')
        })
    })
})
