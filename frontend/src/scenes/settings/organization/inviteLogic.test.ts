import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { organizationLogic } from '../../organizationLogic'
import { inviteLogic } from './inviteLogic'

describe('inviteLogic (guest invites)', () => {
    beforeEach(() => {
        useMocks({
            post: {
                'api/organizations/:id/invites/bulk/': () => [200, []],
            },
        })
        initKeaTests()
        organizationLogic.mount()
        inviteLogic.mount()
    })

    it('canSubmit requires at least one grant when guest mode is on', async () => {
        inviteLogic.actions.setIsGuestInvite(true)
        inviteLogic.actions.updateInviteAtIndex({ target_email: 'guest@acme.io', isValid: true }, 0)
        await expectLogic(inviteLogic).toMatchValues({ canSubmit: false, isGuestInvite: true })

        inviteLogic.actions.addGuestGrant({ team_id: 1, resource: 'dashboard', resource_id: '42', label: 'KPIs' })
        await expectLogic(inviteLogic).toMatchValues({ canSubmit: true })
    })

    it('canSubmit is false for multi-invitee guest invites', async () => {
        inviteLogic.actions.setIsGuestInvite(true)
        inviteLogic.actions.updateInviteAtIndex({ target_email: 'guest1@acme.io', isValid: true }, 0)
        inviteLogic.actions.appendInviteRow()
        inviteLogic.actions.updateInviteAtIndex({ target_email: 'guest2@acme.io', isValid: true }, 1)
        inviteLogic.actions.addGuestGrant({ team_id: 1, resource: 'dashboard', resource_id: '42' })

        await expectLogic(inviteLogic).toMatchValues({ canSubmit: false })
    })

    it('resetGuestState clears grants and flags', async () => {
        inviteLogic.actions.setIsGuestInvite(true)
        inviteLogic.actions.setBypassSsoEnforcement(true)
        inviteLogic.actions.addGuestGrant({ team_id: 1, resource: 'dashboard', resource_id: '42' })
        inviteLogic.actions.resetGuestState()

        await expectLogic(inviteLogic).toMatchValues({
            isGuestInvite: false,
            bypassSsoEnforcement: false,
            guestGrants: [],
        })
    })

    it('switching org level from Guest back to Member clears guest state without losing the invitee', async () => {
        // Simulates what InviteRow.onChange does when the user picks Member after Guest:
        // resetGuestState() then updateInviteAtIndex({level: Member}). The invitee email
        // must be preserved so the user doesn't re-type it, but all guest-only state
        // must clear so we don't ship a member invite with attached grants.
        inviteLogic.actions.updateInviteAtIndex({ target_email: 'guest@acme.io', isValid: true }, 0)
        inviteLogic.actions.setIsGuestInvite(true)
        inviteLogic.actions.addGuestGrant({ team_id: 1, resource: 'dashboard', resource_id: '42' })
        inviteLogic.actions.setBypassSsoEnforcement(true)

        inviteLogic.actions.resetGuestState()
        inviteLogic.actions.updateInviteAtIndex({ level: 1 /* Member */ }, 0)

        await expectLogic(inviteLogic).toMatchValues({
            isGuestInvite: false,
            bypassSsoEnforcement: false,
            guestGrants: [],
        })
        // The invitee email and new level are preserved.
        expect(inviteLogic.values.invitesToSend[0]).toMatchObject({
            target_email: 'guest@acme.io',
            level: 1,
        })
    })

    describe('per-grant access_level', () => {
        it('addGuestGrant defaults access_level to viewer when omitted', async () => {
            inviteLogic.actions.addGuestGrant({
                team_id: 1,
                resource: 'dashboard',
                resource_id: '42',
                label: 'KPIs',
            })
            await expectLogic(inviteLogic).toMatchValues({
                guestGrants: [
                    expect.objectContaining({
                        resource: 'dashboard',
                        resource_id: '42',
                        access_level: 'viewer',
                    }),
                ],
            })
        })

        it('addGuestGrant honors an explicit editor access_level', async () => {
            inviteLogic.actions.addGuestGrant({
                team_id: 1,
                resource: 'dashboard',
                resource_id: '42',
                label: 'KPIs',
                access_level: 'editor',
            })
            await expectLogic(inviteLogic).toMatchValues({
                guestGrants: [expect.objectContaining({ access_level: 'editor' })],
            })
        })

        it('setGuestGrantAccessLevel updates an existing grant in place', async () => {
            inviteLogic.actions.addGuestGrant({
                team_id: 1,
                resource: 'dashboard',
                resource_id: '42',
            })
            inviteLogic.actions.addGuestGrant({
                team_id: 1,
                resource: 'insight',
                resource_id: 'abc',
            })

            inviteLogic.actions.setGuestGrantAccessLevel(1, 'editor')

            await expectLogic(inviteLogic).toMatchValues({
                guestGrants: [
                    expect.objectContaining({ resource: 'dashboard', access_level: 'viewer' }),
                    expect.objectContaining({ resource: 'insight', access_level: 'editor' }),
                ],
            })
        })

        it('switching resource type while editing grants does not drop access_level', async () => {
            // Simulates the flow where the admin adds an editor-level grant, then adds another
            // grant of a different resource type. The first grant's access_level must survive.
            inviteLogic.actions.addGuestGrant({
                team_id: 1,
                resource: 'dashboard',
                resource_id: '42',
                access_level: 'editor',
            })
            inviteLogic.actions.addGuestGrant({
                team_id: 1,
                resource: 'insight',
                resource_id: 'abc',
            })

            await expectLogic(inviteLogic).toMatchValues({
                guestGrants: [
                    expect.objectContaining({ resource: 'dashboard', access_level: 'editor' }),
                    expect.objectContaining({ resource: 'insight', access_level: 'viewer' }),
                ],
            })
        })
    })
})
