import { MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_SECOND_ORGANIZATION_MEMBER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { membersLogic } from 'scenes/organization/membersLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { memberOffboardingLogic } from './memberOffboardingLogic'

const resources = [
    {
        id: 'public_link:dashboard:1:1',
        kind: 'dashboard',
        name: 'Product overview',
        team_id: 1,
        project_name: 'Website',
    },
    {
        id: 'public_link:insight:1:2',
        kind: 'insight',
        name: 'Weekly acquisition',
        team_id: 1,
        project_name: 'Website',
    },
]

describe('memberOffboardingLogic', () => {
    let logic: ReturnType<typeof memberOffboardingLogic.build>
    let submitted: unknown[]

    beforeEach(() => {
        submitted = []
        useMocks({
            get: {
                '/api/organizations/:organization/members/:user/offboarding/': resources,
                '/api/organizations/:organization/members/:user/scoped_api_keys/': { has_keys: false, keys: [] },
            },
            post: {
                '/api/organizations/:organization/members/:user/offboard/': async ({ request }) => {
                    submitted.push(await request.json())
                    return [204, null]
                },
            },
        })
        initKeaTests()
        logic = memberOffboardingLogic()
        logic.mount()
    })

    it('keeps current sharing by default and submits only the links left enabled', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.resources).toEqual(resources)
        expect(logic.values.keep).toEqual(resources.map((resource) => resource.id))
        membersLogic.actions.loadAllMembersSuccess([MOCK_DEFAULT_ORGANIZATION_MEMBER, MOCK_SECOND_ORGANIZATION_MEMBER])
        logic.actions.setKeep(resources[0].id, false)
        await expectLogic(logic, () => logic.actions.remove()).toDispatchActions(['removeSuccess'])
        expect(submitted).toEqual([{ keep: [resources[1].id] }])
        expect(logic.values.member).toBeNull()
        expect(membersLogic.values.members).toEqual([MOCK_DEFAULT_ORGANIZATION_MEMBER])
        expect(membersLogic.values.membersLoading).toBe(false)
    })

    it('disables only the selected public resources when removing the member', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        logic.actions.disableResources([resources[0].id])
        expect(logic.values.keep).toEqual([resources[1].id])
        await expectLogic(logic, () => logic.actions.remove()).toDispatchActions(['removeSuccess'])
        expect(submitted).toEqual([{ keep: [resources[1].id] }])
    })

    it('summarizes the selected resource types, including selections beyond one page', async () => {
        const mixedResources = [
            ...resources,
            { ...resources[0], id: 'dashboard:2' },
            { ...resources[0], id: 'dashboard:3' },
            { ...resources[0], id: 'notebook:1', kind: 'notebook' },
            { ...resources[0], id: 'recording:1', kind: 'recording' },
        ]
        useMocks({ get: { '/api/organizations/:organization/members/:user/offboarding/': mixedResources } })
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.getSelectionLabel([mixedResources[4].id]).replaceAll('\u00a0', ' ')).toBe('1 notebook')
        expect(
            logic.values.getSelectionLabel(mixedResources.map((resource) => resource.id)).replaceAll('\u00a0', ' ')
        ).toBe('3 dashboards, 1 insight, 1 notebook, 1 recording')
    })

    it('reviews public links, subscriptions and alerts together and keeps them enabled by default', async () => {
        const subscription = { ...resources[0], id: 'subscription:1', kind: 'subscription', name: 'Weekly report' }
        const alert = { ...resources[0], id: 'alert:1', kind: 'alert', name: 'Usage alert' }
        useMocks({
            get: { '/api/organizations/:organization/members/:user/offboarding/': [...resources, subscription, alert] },
        })
        await expectLogic(logic, () => logic.actions.open(MOCK_SECOND_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.publicResources).toEqual(resources)
        expect(logic.values.subscriptions).toEqual([subscription, alert])
        expect(logic.values.keep).toEqual([...resources.map((resource) => resource.id), subscription.id, alert.id])
        logic.actions.disableResources([subscription.id])
        await expectLogic(logic, () => logic.actions.remove()).toDispatchActions(['removeSuccess'])
        expect(submitted).toEqual([{ keep: [...resources.map((resource) => resource.id), alert.id] }])
    })

    it('does not retain public links when leaving the organization yourself', async () => {
        await expectLogic(logic, () => logic.actions.open(MOCK_DEFAULT_ORGANIZATION_MEMBER)).toFinishAllListeners()
        expect(logic.values.keep).toEqual([])
        await expectLogic(logic, () => logic.actions.remove()).toDispatchActions(['removeSuccess'])
        expect(submitted).toEqual([{ keep: [] }])
    })

    it('blocks removal when the resource review fails and permits retry', async () => {
        useMocks({
            get: {
                '/api/organizations/:organization/members/:user/offboarding/': () => [
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
        useMocks({ get: { '/api/organizations/:organization/members/:user/offboarding/': resources } })
        await expectLogic(logic, () => logic.actions.loadResources()).toDispatchActions(['loadResourcesSuccess'])
        expect(logic.values.loadError).toBeNull()
    })
})
