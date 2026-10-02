import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sceneTitleSameNameLogic } from './sceneTitleSameNameLogic'

describe('sceneTitleSameNameLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/file_system/': {
                    count: 4,
                    results: [
                        {
                            id: 'a',
                            path: 'Unfiled/Dashboards/Analytics basics',
                            type: 'dashboard',
                            ref: '1',
                            href: '/dashboard/1',
                        },
                        { id: 'b', path: 'Team/analytics BASICS ', type: 'dashboard', ref: '2', href: '/dashboard/2' },
                        {
                            id: 'c',
                            path: 'Unfiled/Dashboards/Analytics basics (wizard)',
                            type: 'dashboard',
                            ref: '3',
                            href: '/dashboard/3',
                        },
                        {
                            id: 'd',
                            path: 'Unfiled/Dashboards/Analytics basics',
                            type: 'dashboard',
                            ref: '4',
                            href: '/dashboard/4',
                        },
                    ],
                },
            },
        })
        initKeaTests()
    })

    it('keeps only other items whose name matches exactly', async () => {
        const logic = sceneTitleSameNameLogic({ type: 'dashboard', itemRef: '4', name: 'Analytics basics' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadSameNameItemsSuccess'])
        expect(logic.values.sameNameItems.map((entry) => entry.ref)).toEqual(['1', '2'])
    })
})
