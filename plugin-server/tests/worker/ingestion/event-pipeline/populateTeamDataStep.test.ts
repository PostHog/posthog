import { DB } from '~/utils/db/db'
import { TeamManager } from '~/utils/team-manager'

import { Hub, PipelineEvent, Team } from '../../../../src/types'
import { createEventsToDropByToken } from '../../../../src/utils/db/hub'
import { UUIDT } from '../../../../src/utils/utils'
import { populateTeamDataStep } from '../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep'
import { getMetricValues, resetMetrics } from '../../../helpers/metrics'

const pipelineEvent: PipelineEvent = {
    event: '$pageview',
    properties: { foo: 'bar' },
    timestamp: '2020-02-23T02:15:00Z',
    now: '2020-02-23T02:15:00Z',
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'https://example.com',
    uuid: new UUIDT().toString(),
}

// @ts-expect-error TODO: fix underlying type
const teamTwo: Team = {
    id: 2,
    uuid: 'af95d312-1a0a-4208-b80f-562ddafc9bcd',
    organization_id: '66f3f7bf-44e2-45dd-9901-5dbd93744e3a',
    name: 'testTeam',
    anonymize_ips: false,
    api_token: 'token',
    slack_incoming_webhook: '',
    session_recording_opt_in: false,
    ingested_event: true,
}

const teamTwoToken = 'token'

let hub: Hub

beforeEach(() => {
    resetMetrics()
    const teamManager: TeamManager = {
        getTeamByToken: jest.fn(async (token) => {
            return Promise.resolve(token === teamTwoToken ? teamTwo : null)
        }),

        getTeam: jest.fn((teamId) => {
            if (teamId === 2) {
                return teamTwo
            }
            if (teamId === 3) {
                return { ...teamTwo, person_processing_opt_out: true }
            }
            return null
        }),
    } as unknown as TeamManager

    const db = {
        kafkaProducer: {
            queueMessages: jest.fn(() => Promise.resolve()),
        },
    } as unknown as DB

    hub = {
        eventsToSkipPersonsProcessingByToken: createEventsToDropByToken('2:distinct_id_to_drop'),
        teamManager,
        db,
    } as Hub
})

describe('populateTeamDataStep()', () => {
    it('event with no token is not processed and the step returns null', async () => {
        const response = await populateTeamDataStep(hub, { ...pipelineEvent })
        expect(response).toEqual(null)
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([
            {
                labels: {
                    drop_cause: 'no_token',
                    event_type: 'analytics',
                },
                value: 1,
            },
        ])
    })

    it('event with an invalid token is not processed and the step returns null', async () => {
        const response = await populateTeamDataStep(hub, { ...pipelineEvent, token: 'unknown' })
        expect(response).toEqual(null)
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([
            {
                labels: {
                    drop_cause: 'invalid_token',
                    event_type: 'analytics',
                },
                value: 1,
            },
        ])
    })

    it('event with a valid token keeps its ip', async () => {
        const response = await populateTeamDataStep(hub, { ...pipelineEvent, token: teamTwoToken })

        expect(response?.event).toEqual({ ...pipelineEvent, token: teamTwoToken, ip: '127.0.0.1' })
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([])
    })

    it('event with a valid token for a team with anonymize_ips=true keeps its ip', async () => {
        // NOTE: The IP is intentionally kept in `populateTeamDataStep` so that it is still
        // available for plugins. It is later removed by `prepareEventStep`.
        jest.mocked(hub.teamManager.getTeamByToken).mockResolvedValue({ ...teamTwo, anonymize_ips: true })
        const response = await populateTeamDataStep(hub, { ...pipelineEvent, token: teamTwoToken })

        expect(response?.event).toEqual({ ...pipelineEvent, token: teamTwoToken, ip: '127.0.0.1' })
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([])
    })

    it('event with a team_id value is returned unchanged', async () => {
        const input = { ...pipelineEvent, team_id: 2 }
        const response = await populateTeamDataStep(hub, input)
        expect(response?.event).toEqual(input)
    })

    it('event with a team_id whose team is opted-out from person processing', async () => {
        const input = { ...pipelineEvent, team_id: 3 }
        const response = await populateTeamDataStep(hub, input)
        expect(response?.team.person_processing_opt_out).toBe(true)
        expect(response?.event.properties?.$process_person_profile).toBe(false)
    })

    it('event that is in the skip list', async () => {
        const input = { ...pipelineEvent, team_id: 2, distinct_id: 'distinct_id_to_drop' }
        const response = await populateTeamDataStep(hub, input)
        expect(response?.event.properties?.$process_person_profile).toBe(false)
    })

    it('PG errors are propagated up to trigger retries', async () => {
        jest.mocked(hub.teamManager.getTeamByToken).mockRejectedValueOnce(new Error('retry me'))
        await expect(async () => {
            await populateTeamDataStep(hub, { ...pipelineEvent, token: teamTwoToken })
        }).rejects.toThrowError('retry me')
    })

    describe('validates eventUuid', () => {
        test('invalid uuid string returns an error', async () => {
            const event: PipelineEvent = {
                ...pipelineEvent,
                team_id: 2,
                uuid: 'i_am_not_a_uuid',
            }

            await expect(populateTeamDataStep(hub, event)).resolves.toEqual(null)
        })
        test('null value in eventUUID returns an error', async () => {
            const event = {
                ...pipelineEvent,
                team_id: 2,
                uuid: null as any,
            }

            await expect(populateTeamDataStep(hub, event)).resolves.toEqual(null)
        })
    })
})
