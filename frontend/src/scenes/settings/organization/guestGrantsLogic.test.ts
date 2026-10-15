import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { guestGrantsLogic } from './guestGrantsLogic'
import { GuestGrant, inviteLogic } from './inviteLogic'

const PREVIEW = [
    {
        resource: 'dashboard',
        id: '12',
        name: 'Client KPIs',
        includes: [{ resource: 'insight', id: '7', name: 'Weekly pageviews' }],
    },
]

describe('guestGrantsLogic', () => {
    let logic: ReturnType<typeof guestGrantsLogic.build>
    let previewRequests: unknown[]

    beforeEach(() => {
        previewRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/dashboards/': () => [200, { results: [{ id: 12, name: 'Client KPIs' }] }],
            },
            post: {
                '/api/organizations/:organization_id/invites/guest_preview/': async ({ request }) => {
                    previewRequests.push(await request.json())
                    return [200, { results: PREVIEW }]
                },
            },
        })
        initKeaTests(true, undefined, undefined, MOCK_DEFAULT_ORGANIZATION)
        inviteLogic.mount()
        inviteLogic.actions.updateInviteAtIndex({ level: OrganizationMembershipLevel.Guest }, 0)
        logic = guestGrantsLogic({ inviteIndex: 0 })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        inviteLogic.unmount()
    })

    const grants = (): GuestGrant[] => inviteLogic.values.invitesToSend[0].guest_grants

    it.each([
        ['adds an item, then removes it', ['item', 'item'], []],
        ['replaces the items of a type with all of them', ['item', 'all'], [{ resource: 'dashboard', id: null }]],
        ['clears all of them', ['all', 'all'], []],
    ])('%s', async (_name, toggles, expected) => {
        for (const toggle of toggles) {
            if (toggle === 'all') {
                logic.actions.toggleAll('dashboard')
            } else {
                logic.actions.toggleObject('dashboard', { id: '12', name: 'Client KPIs' })
            }
        }
        await expectLogic(logic).toFinishAllListeners()
        expect(grants()).toEqual(expected)
    })

    it('keeps the grants of other types when it selects all of one type', async () => {
        logic.actions.toggleObject('notebook', { id: 'nb-1', name: 'Onboarding review' })
        logic.actions.toggleObject('dashboard', { id: '12', name: 'Client KPIs' })
        logic.actions.toggleAll('dashboard')
        await expectLogic(logic).toFinishAllListeners()
        expect(grants()).toEqual([
            { resource: 'notebook', id: 'nb-1', name: 'Onboarding review' },
            { resource: 'dashboard', id: null },
        ])
    })

    it('previews the selected grants without their names', async () => {
        logic.actions.toggleObject('dashboard', { id: '12', name: 'Client KPIs' })
        await expectLogic(logic).toDispatchActions(['loadPreviewSuccess']).toMatchValues({ preview: PREVIEW })
        expect(previewRequests[previewRequests.length - 1]).toEqual({
            project_id: expect.any(Number),
            grants: [{ resource: 'dashboard', id: '12' }],
        })
    })
})
