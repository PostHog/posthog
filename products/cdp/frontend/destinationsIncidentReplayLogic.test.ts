import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { destinationsIncidentReplayLogic } from './destinationsIncidentReplayLogic'

const MASKED_ONLY_ID = '019d244c-42c9-0000-ec6c-752c8b265c4f'
const FAILED_ONLY_ID = '019d9146-223a-0000-8165-1a3489e88b3d'
const DELETED_ID = '019f3834-8dbd-0000-4b19-073031109b21'

describe('destinationsIncidentReplayLogic', () => {
    let logic: ReturnType<typeof destinationsIncidentReplayLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [
                    200,
                    {
                        results: [
                            [FAILED_ONLY_ID, 224],
                            [DELETED_ID, 3],
                        ],
                    },
                ],
            },
            get: {
                '/api/projects/:team_id/hog_functions/masked_secrets/': () => [
                    200,
                    [
                        {
                            id: MASKED_ONLY_ID,
                            name: 'Customer.io',
                            type: 'destination',
                            enabled: true,
                            input_keys: ['api_key'],
                            draft_input_keys: [],
                        },
                    ],
                ],
                '/api/projects/:team_id/hog_functions/:id/': (req) => {
                    if (req.params.id === MASKED_ONLY_ID) {
                        return [200, { id: MASKED_ONLY_ID, name: 'Customer.io', type: 'destination', enabled: true }]
                    }
                    if (req.params.id === FAILED_ONLY_ID) {
                        return [200, { id: FAILED_ONLY_ID, name: 'HubSpot', type: 'destination', enabled: true }]
                    }
                    return [404, { detail: 'Not found.' }]
                },
            },
        })
        initKeaTests()
        logic = destinationsIncidentReplayLogic()
        logic.mount()
    })

    it('lists destinations found by either signal and drops deleted ones', async () => {
        await expectLogic(logic, () => logic.actions.loadAffectedDestinations()).toDispatchActions([
            'loadAffectedDestinationsSuccess',
        ])

        expect(logic.values.affectedDestinations).toEqual([
            {
                id: FAILED_ONLY_ID,
                name: 'HubSpot',
                type: 'destination',
                failedCount: 224,
                needsCredentials: false,
                enabled: true,
            },
            {
                id: MASKED_ONLY_ID,
                name: 'Customer.io',
                type: 'destination',
                failedCount: 0,
                needsCredentials: true,
                enabled: true,
            },
        ])
    })

    it('still surfaces the recovery path when the failed-count query errors', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [500, { detail: 'Query timed out' }],
            },
        })

        await expectLogic(logic, () => logic.actions.loadAffectedDestinations()).toDispatchActions([
            'loadAffectedDestinationsSuccess',
        ])

        expect(logic.values.affectedDestinations).toEqual([
            {
                id: MASKED_ONLY_ID,
                name: 'Customer.io',
                type: 'destination',
                failedCount: 0,
                needsCredentials: true,
                enabled: true,
            },
        ])
    })
})
