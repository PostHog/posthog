import { organizationAllowsMembersToInvite } from './permissioning'

describe('organizationAllowsMembersToInvite', () => {
    test.each([
        // Mirrors UserCanInvitePermission (posthog/permissions.py): without the entitlement,
        // the backend allows any member to invite regardless of members_can_invite.
        [{ members_can_invite: false }, false, true],
        [{ members_can_invite: true }, false, true],
        [null, false, true],
        // With the entitlement, members_can_invite gates access, and a missing/null value
        // defaults to permissive to match the model's `default=True`.
        [{ members_can_invite: true }, true, true],
        [{ members_can_invite: false }, true, false],
        [{ members_can_invite: undefined }, true, true],
        [null, true, true],
    ] as const)('org=%p, hasEntitlement=%p -> %p', (org, hasOrganizationInviteSettingsEntitlement, expected) => {
        expect(organizationAllowsMembersToInvite(org, hasOrganizationInviteSettingsEntitlement)).toBe(expected)
    })
})
