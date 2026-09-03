import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    destinationsIncidentReplayLogic,
    incidentCountWindowStart,
    incidentReplayWindow,
} from './destinationsIncidentReplayLogic'

const MASKED_ONLY_ID = '019d244c-42c9-0000-ec6c-752c8b265c4f'
const FAILED_ONLY_ID = '019d9146-223a-0000-8165-1a3489e88b3d'
const DELETED_ID = '019f3834-8dbd-0000-4b19-073031109b21'
const NO_SECRET_ID = '019f3834-8dbd-0000-4b19-073031109b22'

const SECRET_SCHEMA = [{ key: 'api_key', type: 'string', label: 'API key', secret: true }]
const INTEGRATION_SCHEMA = [{ key: 'slack_workspace', type: 'integration', label: 'Slack workspace' }]

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
                            [NO_SECRET_ID, 91],
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
                        return [
                            200,
                            {
                                id: MASKED_ONLY_ID,
                                name: 'Customer.io',
                                type: 'destination',
                                enabled: true,
                                inputs_schema: SECRET_SCHEMA,
                            },
                        ]
                    }
                    if (req.params.id === FAILED_ONLY_ID) {
                        return [
                            200,
                            {
                                id: FAILED_ONLY_ID,
                                name: 'HubSpot',
                                type: 'destination',
                                enabled: true,
                                inputs_schema: SECRET_SCHEMA,
                            },
                        ]
                    }
                    if (req.params.id === NO_SECRET_ID) {
                        return [
                            200,
                            {
                                id: NO_SECRET_ID,
                                name: 'Slack',
                                type: 'destination',
                                enabled: true,
                                inputs_schema: INTEGRATION_SCHEMA,
                            },
                        ]
                    }
                    return [404, { detail: 'Not found.' }]
                },
            },
        })
        initKeaTests()
        logic = destinationsIncidentReplayLogic()
        logic.mount()
    })

    it('excludes a failing destination that holds no secret the incident could clear', async () => {
        await expectLogic(logic, () => logic.actions.loadAffectedDestinations()).toDispatchActions([
            'loadAffectedDestinationsSuccess',
        ])

        expect(logic.values.affectedDestinations.map((row) => row.id)).not.toContain(NO_SECRET_ID)
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

    describe('incidentCountWindowStart', () => {
        // The replay sends the incident start as UTC. If the count read it as team-local wall time
        // instead, the two would cover spans a whole timezone offset apart.
        it('renders the same instant the replay sends, in the team timezone', () => {
            expect(incidentCountWindowStart('UTC')).toEqual('2026-08-18 13:30:00.000')
            expect(incidentCountWindowStart('US/Pacific')).toEqual('2026-08-18 06:30:00.000')
            expect(incidentCountWindowStart('Europe/Berlin')).toEqual('2026-08-18 15:30:00.000')
        })
    })

    describe('incidentReplayWindow', () => {
        it('uses the incident start while the incident is within the 30-day cap', () => {
            expect(incidentReplayWindow(new Date('2026-08-25T00:00:00.000Z'))).toEqual({
                window_start: '2026-08-18T13:30:00.000Z',
                window_end: '2026-08-25T00:00:00.000Z',
            })
        })

        it('clamps the start to 30 days once the incident is older than the cap', () => {
            const { window_start, window_end } = incidentReplayWindow(new Date('2026-10-01T00:00:00.000Z'))
            expect(window_start).toEqual('2026-09-01T00:00:00.000Z')
            expect(window_end).toEqual('2026-10-01T00:00:00.000Z')
            // Stays within the rerun endpoint's 30-day cap, so the request is not rejected.
            const spanDays = (new Date(window_end).getTime() - new Date(window_start).getTime()) / (24 * 60 * 60 * 1000)
            expect(spanDays).toBeLessThanOrEqual(30)
        })
    })
})
