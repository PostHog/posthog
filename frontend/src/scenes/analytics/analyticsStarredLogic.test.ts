import { expectLogic } from 'kea-test-utils'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { analyticsStarredLogic } from './analyticsStarredLogic'

describe('analyticsStarredLogic', () => {
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

    it('keeps only analytics items and collections, and unstars an item whatever subtype it was starred as', async () => {
        const logic = analyticsStarredLogic()
        logic.mount()
        await expectLogic(projectTreeDataLogic).toDispatchActions(['loadShortcutsSuccess'])

        expect(logic.values.starredAnalytics.map((starred) => starred.key)).toEqual([
            'folder:Growth',
            'insight:abc123',
            'dashboard:7',
        ])

        await expectLogic(logic, () =>
            logic.actions.toggleStarred({ type: 'insight', ref: 'abc123', name: 'Signups' })
        ).toDispatchActions(['deleteShortcutSuccess'])
        expect(requests).toEqual(['delete sc-insight'])
        expect(logic.values.starredAnalytics.map((starred) => starred.key)).toEqual(['folder:Growth', 'dashboard:7'])
    })
})
