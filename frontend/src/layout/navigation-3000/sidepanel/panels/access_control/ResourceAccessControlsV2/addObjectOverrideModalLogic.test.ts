import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { addObjectOverrideModalLogic } from './addObjectOverrideModalLogic'

describe('addObjectOverrideModalLogic', () => {
    let logic: ReturnType<typeof addObjectOverrideModalLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:id/access_control_member_objects': { results: [] },
                '/api/projects/:id/access_control_member_properties': { results: [] },
                '/api/projects/:id/access_control_defaults': {
                    object_rule_resources: [
                        {
                            resource: 'action',
                            available_access_levels: ['none', 'viewer', 'editor', 'manager'],
                            minimum_access_level: 'viewer',
                        },
                        {
                            resource: 'dashboard',
                            available_access_levels: ['none', 'viewer', 'editor', 'manager'],
                            minimum_access_level: 'none',
                        },
                    ],
                },
                '/api/projects/:id/access_control_object_search': ({ request }) => [
                    200,
                    {
                        results:
                            new URL(request.url).searchParams.get('resource') === 'insight'
                                ? [{ id: 'insight-pk', name: 'Weekly signups' }]
                                : [{ id: 'dashboard-pk', name: 'Growth dashboard' }],
                    },
                ],
            },
        })
        initKeaTests()
        logic = addObjectOverrideModalLogic.build({
            projectId: '997',
            scopeType: 'member',
            subjectId: 'member-1',
        })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('drops the previous options when a pasted URL switches the resource', async () => {
        await expectLogic(logic, () => logic.actions.openModal()).toDispatchActions(['loadObjectOptionsSuccess'])
        expect(logic.values.displayObjectOptions.map((o) => o.id)).toEqual(['dashboard-pk'])

        // The resource and the picked object have to describe the same thing. Leaving the dashboard
        // options behind lets the user pick one under the insight type, which writes a rule for
        // {resource: insight, resource_id: <dashboard pk>}
        await expectLogic(logic, () =>
            logic.actions.setSearch('https://eu.posthog.com/project/997/insights/abc123')
        ).toDispatchActions(['resolveObjectUrl', 'objectResolvedFromUrl', 'loadObjectOptionsSuccess'])

        expect(logic.values.resource).toEqual('insight')
        expect(logic.values.objectId).toEqual('insight-pk')
        expect(logic.values.displayObjectOptions.map((o) => o.id)).toEqual(['insight-pk'])
    })

    it('raises the level to the resource minimum when switching to a resource that enforces one', async () => {
        await expectLogic(logic, () => logic.actions.openModal()).toDispatchActions(['loadObjectOptionsSuccess'])
        expect(logic.values.level).toEqual('none')

        // "No access" is below action's minimum, so keeping it would 400 on save
        await expectLogic(logic, () => logic.actions.setResource('action')).toDispatchActions(['setLevel'])
        expect(logic.values.level).toEqual('viewer')

        // Switching back only clamps upward; the picked level is kept
        await expectLogic(logic, () => logic.actions.setResource('dashboard'))
        expect(logic.values.level).toEqual('viewer')
    })
})
