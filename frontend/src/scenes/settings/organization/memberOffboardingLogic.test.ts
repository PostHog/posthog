import { MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_SECOND_ORGANIZATION_MEMBER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { membersLogic } from 'scenes/organization/membersLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { memberOffboardingLogic } from './memberOffboardingLogic'

const resources = [
    {
        id: 'public_link:dashboard:1:1',
        resource_id: '1',
        kind: 'dashboard',
        name: 'Product overview',
        team_id: 1,
        project_name: 'Website',
    },
    {
        id: 'public_link:insight:1:2',
        resource_id: '2',
        kind: 'insight',
        name: 'Weekly acquisition',
        team_id: 1,
        project_name: 'Website',
    },
]

describe('memberOffboardingLogic', () => {
    let logic: ReturnType<typeof memberOffboardingLogic.build>
    let submitted: unknown[]
    let updates: unknown[]

    beforeEach(() => {
        submitted = []
        updates = []
        useMocks({
            get: {
                '/api/organizations/:organization/members/:user/offboarding_preview/': resources,
                '/api/organizations/:organization/members/:user/scoped_api_keys/': { has_keys: false, keys: [] },
            },
            patch: {
                '/api/projects/:project/:kind/:resource/sharing/': async ({ request }) => {
                    updates.push({ path: new URL(request.url).pathname, body: await request.json() })
                    return [204, null]
                },
            },
            delete: {
                '/api/organizations/:organization/members/:user/': () => {
                    submitted.push('remove')
                    return [204, null]
                },
            },
        })
        initKeaTests()
        logic = memberOffboardingLogic()
        logic.mount()
    })

    it('saves toggles immediately and removes the member without changing resources again', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.resources).toEqual(resources)
        expect(logic.values.keep).toEqual(resources.map((resource) => resource.id))
        membersLogic.actions.loadAllMembersSuccess([MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_SECOND_ORGANIZATION_MEMBER])
        await expectLogic(logic, () => {
            logic.actions.setKeep(resources[0].id, false)
            expect(logic.values.savingResourceIds).toEqual([resources[0].id])
        }).toFinishAllListeners()
        expect(logic.values.savingResourceIds).toEqual([])
        expect(updates).toEqual([{ path: '/api/projects/1/dashboards/1/sharing/', body: { enabled: false } }])
        expect(submitted).toEqual([])
        await expectLogic(logic, () => logic.actions.remove()).toDispatchActions(['removeSuccess'])
        expect(submitted).toEqual(['remove'])
        expect(logic.values.member).toBeNull()
        expect(membersLogic.values.members).toEqual([MOCK_DEFAULT_ORGANIZATION_MEMBER])
        expect(membersLogic.values.membersLoading).toBe(false)
    })

    it('disables selected resources immediately and cancellation does not undo the change', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.disableResources([resources[0].id])).toFinishAllListeners()
        expect(updates).toEqual([{ path: '/api/projects/1/dashboards/1/sharing/', body: { enabled: false } }])
        expect(logic.values.keep).toEqual([resources[1].id])
        logic.actions.close()
        expect(submitted).toEqual([])
        expect(updates).toHaveLength(1)
    })

    it('keeps the previous toggle state when saving fails and allows retry', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        useMocks({
            patch: {
                '/api/projects/:project/:kind/:resource/sharing/': () => [500, { detail: 'Save failed' }],
            },
        })
        await expectLogic(logic, () => logic.actions.setKeep(resources[0].id, false)).toDispatchActions([
            'saveResourcesSuccess',
        ])
        expect(logic.values.keep).toEqual(resources.map((resource) => resource.id))
        expect(logic.values.savingResourcesLoading).toBe(false)
        expect(logic.values.savingResourceIds).toEqual([])
        useMocks({
            patch: { '/api/projects/:project/:kind/:resource/sharing/': () => [204, null] },
        })
        await expectLogic(logic, () => logic.actions.setKeep(resources[0].id, false)).toDispatchActions([
            'saveResourcesSuccess',
        ])
        expect(logic.values.keep).toEqual([resources[1].id])
        await expectLogic(logic, () => logic.actions.setKeep(resources[0].id, true)).toDispatchActions([
            'saveResourcesSuccess',
        ])
        expect(logic.values.keep).toContain(resources[0].id)
    })

    it('explains why the organization policy prevents re-enabling a public link', async () => {
        const toast = jest.spyOn(lemonToast, 'error')
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.setKeep(resources[0].id, false)).toFinishAllListeners()
        useMocks({
            patch: {
                '/api/projects/1/dashboards/1/sharing/': () => [
                    403,
                    { detail: 'Public sharing is disabled for this organization.' },
                ],
            },
        })
        await expectLogic(logic, () => logic.actions.setKeep(resources[0].id, true)).toFinishAllListeners()
        expect(logic.values.keep).toEqual([resources[1].id])
        expect(logic.values.savingResourceIds).toEqual([])
        expect(toast).toHaveBeenLastCalledWith(
            "Couldn't update Product overview. Public sharing is disabled for this organization."
        )
        toast.mockRestore()
    })

    it('keeps successful bulk changes when another resource fails', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        useMocks({ patch: { '/api/projects/1/insights/2/sharing/': () => [403, { detail: 'Cannot edit' }] } })
        await expectLogic(logic, () =>
            logic.actions.disableResources(resources.map((resource) => resource.id))
        ).toFinishAllListeners()
        expect(logic.values.keep).toEqual([resources[1].id])
        expect(logic.values.savingResourcesLoading).toBe(false)
    })

    it('summarizes the selected resource types, including selections beyond one page', async () => {
        const mixedResources = [
            ...resources,
            { ...resources[0], id: 'dashboard:2' },
            { ...resources[0], id: 'dashboard:3' },
            { ...resources[0], id: 'notebook:1', kind: 'notebook' },
            { ...resources[0], id: 'recording:1', kind: 'recording' },
        ]
        useMocks({ get: { '/api/organizations/:organization/members/:user/offboarding_preview/': mixedResources } })
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.getSelectionLabel([mixedResources[4].id]).replaceAll('\u00a0', ' ')).toBe('1 notebook')
        expect(
            logic.values.getSelectionLabel(mixedResources.map((resource) => resource.id)).replaceAll('\u00a0', ' ')
        ).toBe('3 dashboards, 1 insight, 1 notebook, 1 recording')
    })

    it('skips the resource review when leaving the organization yourself', async () => {
        useMocks({ get: { '/api/organizations/:organization/members/:user/offboarding_preview/': [] } })
        await expectLogic(logic, () => logic.actions.open(MOCK_DEFAULT_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.resources).toEqual([])
        expect(logic.values.keep).toEqual([])
        await expectLogic(logic, () => logic.actions.remove()).toDispatchActions(['removeSuccess'])
        expect(submitted).toEqual(['remove'])
    })

    it('blocks removal when the resource review fails and permits retry', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization/members/:user/offboarding_preview/': () => [
                    500,
                    { detail: 'Review unavailable' },
                ],
            },
        })
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toDispatchActions([
            'loadResourcesFailure',
        ])
        await expectLogic(logic, () => logic.actions.remove()).toFinishAllListeners()
        expect(submitted).toEqual([])
        expect(logic.values.loadError).toBeTruthy()
        useMocks({ get: { '/api/organizations/:organization/members/:user/offboarding_preview/': resources } })
        await expectLogic(logic, () => logic.actions.loadResources()).toDispatchActions(['loadResourcesSuccess'])
        expect(logic.values.loadError).toBeNull()
    })
})
