import { expectLogic } from 'kea-test-utils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { analyticsPinnedLogic } from './analyticsPinnedLogic'

describe('analyticsPinnedLogic', () => {
    let requests: string[]

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/file_system_shortcut/': {
                    results: [
                        { id: 'sc-product', type: 'session_replay', path: 'Session replay', href: '/replay' },
                        { id: 'sc-home', type: 'folder', path: 'Ada', ref: 'Users/Ada' },
                        { id: 'sc-growth', type: 'folder', path: 'Growth', ref: 'Growth' },
                        { id: 'sc-insight', type: 'insight/trends', path: 'Signups', ref: 'abc123' },
                        { id: 'sc-dashboard', type: 'dashboard', path: 'KPIs', ref: '7', href: '/dashboard/7' },
                    ],
                },
            },
            delete: {
                '/api/projects/:team_id/file_system_shortcut/:id/': ({ params }) => {
                    requests.push(`delete ${params.id}`)
                    return [204, null]
                },
            },
        })
        initKeaTests()
    })

    it('keeps only analytics items and collections, and unpins an item whatever subtype it was pinned as', async () => {
        const logic = analyticsPinnedLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        expect(logic.values.pinnedAnalytics.map((pinned) => pinned.key)).toEqual([
            'folder:Growth',
            'insight:abc123',
            'dashboard:7',
        ])

        await expectLogic(logic, () =>
            logic.actions.togglePinned({ type: 'insight', ref: 'abc123', name: 'Signups' })
        ).toDispatchActions(projectTreeDataLogic, ['deleteShortcutSuccess'])
        expect(requests).toEqual(['delete sc-insight'])
        expect(logic.values.pinnedAnalytics.map((pinned) => pinned.key)).toEqual(['folder:Growth', 'dashboard:7'])
    })
})
