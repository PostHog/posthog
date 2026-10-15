import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { guestGrantsLogic } from './guestGrantsLogic'
import { GuestGrant, inviteLogic } from './inviteLogic'

const DASHBOARD_PREVIEW = {
    resource: 'dashboard',
    id: '12',
    name: 'Client KPIs',
    includes: [{ resource: 'insight', id: '7', name: 'Weekly pageviews' }],
}
const NOTEBOOK_PREVIEW = { resource: 'notebook', id: 'nb-1', name: 'Onboarding review', includes: [] }

describe('guestGrantsLogic', () => {
    let logic: ReturnType<typeof guestGrantsLogic.build>
    let listRequests: Record<string, number>
    let previewRequests: { grants: GuestGrant[] }[]

    beforeEach(() => {
        listRequests = { dashboard: 0, insight: 0, notebook: 0 }
        previewRequests = []
        useMocks({
            get: {
                '/api/projects/:team_id/dashboards/': () => {
                    listRequests.dashboard += 1
                    return [200, { count: 1, results: [{ id: 12, name: 'Client KPIs' }] }]
                },
                '/api/projects/:team_id/insights/': () => {
                    listRequests.insight += 1
                    return [200, { count: 0, results: [] }]
                },
                '/api/projects/:team_id/notebooks/': () => {
                    listRequests.notebook += 1
                    return [200, { count: 1, results: [{ id: 'nb-1', title: 'Onboarding review' }] }]
                },
            },
            post: {
                '/api/organizations/:organization_id/invites/guest_preview/': async ({ request }) => {
                    const body = (await request.json()) as { grants: GuestGrant[] }
                    previewRequests.push(body)
                    return [
                        200,
                        {
                            results: body.grants.map((grant) =>
                                grant.resource === 'dashboard' ? DASHBOARD_PREVIEW : NOTEBOOK_PREVIEW
                            ),
                        },
                    ]
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

    it('loads each list once and switches types from the cache', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setActiveResource('notebook')
        await expectLogic(logic).toMatchValues({
            options: [{ id: 'nb-1', name: 'Onboarding review' }],
            optionsLoading: false,
        })
        logic.actions.setActiveResource('dashboard')
        await expectLogic(logic).toFinishAllListeners()
        expect(listRequests).toEqual({ dashboard: 1, insight: 1, notebook: 1 })
    })

    it('filters the cached list while the search runs', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setActiveResource('notebook')
        logic.actions.setSearch('onboard')
        await expectLogic(logic).toMatchValues({ options: [{ id: 'nb-1', name: 'Onboarding review' }] })
        logic.actions.setSearch('pricing')
        await expectLogic(logic).toMatchValues({ options: [] })
    })

    it('shows a pick at once and previews only the new pick', async () => {
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.toggleObject('dashboard', { id: '12', name: 'Client KPIs' })
        await expectLogic(logic).toMatchValues({
            previewItems: [{ resource: 'dashboard', id: '12', name: 'Client KPIs', includes: [], loading: true }],
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.toggleObject('notebook', { id: 'nb-1', name: 'Onboarding review' })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.toggleObject('dashboard', { id: '12', name: 'Client KPIs' })
        await expectLogic(logic).toFinishAllListeners()

        expect(previewRequests.map((request) => request.grants)).toEqual([
            [{ resource: 'dashboard', id: '12' }],
            [{ resource: 'notebook', id: 'nb-1' }],
        ])
        expect(logic.values.previewItems).toEqual([{ ...NOTEBOOK_PREVIEW, loading: false }])
    })
})
