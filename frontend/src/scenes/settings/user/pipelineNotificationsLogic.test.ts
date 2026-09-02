import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { pipelineNotificationsLogic } from './pipelineNotificationsLogic'

describe('pipelineNotificationsLogic', () => {
    let logic: ReturnType<typeof pipelineNotificationsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_functions/': { results: [], next: null },
                '/api/projects/:team_id/pipeline_destination_configs/': { results: [], next: null },
                '/api/projects/1/batch_exports/': {
                    results: [{ id: 'be-1', name: 'Nightly export', team_id: 1 }],
                    next: null,
                },
                '/api/projects/2/batch_exports/': {
                    results: [{ id: 'be-2', name: 'Hourly export', team_id: 2 }],
                    next: null,
                },
            },
        })
        initKeaTests()
        userLogic.mount()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            teams: [
                { ...MOCK_DEFAULT_TEAM, id: 1, name: 'Project A' },
                { ...MOCK_DEFAULT_TEAM, id: 2, name: 'Project B' },
            ],
        })
        logic = pipelineNotificationsLogic()
        logic.mount()
    })

    it('lists the batch exports of every project', async () => {
        logic.actions.loadPipelines()
        await expectLogic(logic).toDispatchActions(['loadPipelinesSuccess'])

        expect(logic.values.pipelines).toEqual([
            expect.objectContaining({
                id: 'batch_export:be-1',
                name: 'Nightly export',
                kind: 'batch_export',
                teamId: 1,
                teamName: 'Project A',
            }),
            expect.objectContaining({
                id: 'batch_export:be-2',
                name: 'Hourly export',
                kind: 'batch_export',
                teamId: 2,
                teamName: 'Project B',
            }),
        ])
    })
})
