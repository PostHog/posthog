import { DB } from '~/utils/db/db'
import { TeamManager } from '~/utils/team-manager'

import { resolveTeam } from '../../../src/ingestion/event-preprocessing/resolve-team'
import { Hub, IncomingEvent, Team } from '../../../src/types'
import { getMetricValues, resetMetrics } from '../../helpers/metrics'

const pipelineEvent = {
    event: '$pageview',
    properties: { foo: 'bar' },
    timestamp: '2020-02-23T02:15:00Z',
    now: '2020-02-23T02:15:00Z',
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'https://example.com',
    uuid: '123e4567-e89b-12d3-a456-426614174000',
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
        teamManager,
        db,
    } as Hub
})

describe('resolveTeam()', () => {
    it('event with no token is not processed and the step returns null', async () => {
        const incomingEvent: IncomingEvent = {
            event: { ...pipelineEvent },
            message: {} as any,
        }
        const response = await resolveTeam(hub, incomingEvent)
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
        const incomingEvent: IncomingEvent = {
            event: { ...pipelineEvent, token: 'unknown' },
            message: {} as any,
        }
        const response = await resolveTeam(hub, incomingEvent)
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

    it('event with a valid token calls getTeamByToken with correct token', async () => {
        const incomingEvent: IncomingEvent = {
            event: { ...pipelineEvent, token: teamTwoToken },
            message: {} as any,
        }
        const response = await resolveTeam(hub, incomingEvent)
        expect(response?.event).toEqual({ ...pipelineEvent, token: teamTwoToken })
        expect(response?.team).toEqual(teamTwo)
        expect(hub.teamManager.getTeamByToken).toHaveBeenCalledWith(teamTwoToken)
        expect(hub.teamManager.getTeam).not.toHaveBeenCalled()
    })

    it('event with team_id but no token is dropped', async () => {
        const incomingEvent: IncomingEvent = {
            event: { ...pipelineEvent, team_id: 3 },
            message: {} as any,
        }
        const response = await resolveTeam(hub, incomingEvent)
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
        expect(hub.teamManager.getTeam).not.toHaveBeenCalled()
        expect(hub.teamManager.getTeamByToken).not.toHaveBeenCalled()
    })

    it('event with both team_id and token uses token for team resolution', async () => {
        const incomingEvent: IncomingEvent = {
            event: { ...pipelineEvent, team_id: 3, token: teamTwoToken },
            message: {} as any,
        }
        const response = await resolveTeam(hub, incomingEvent)
        expect(response?.event).toEqual({ ...pipelineEvent, team_id: 3, token: teamTwoToken })
        expect(response?.team).toEqual(teamTwo)
        expect(hub.teamManager.getTeamByToken).toHaveBeenCalledWith(teamTwoToken)
        expect(hub.teamManager.getTeam).not.toHaveBeenCalled()
    })

    it('PG errors are propagated up to trigger retries', async () => {
        jest.mocked(hub.teamManager.getTeamByToken).mockRejectedValueOnce(new Error('retry me'))
        const incomingEvent: IncomingEvent = {
            event: { ...pipelineEvent, token: teamTwoToken },
            message: {} as any,
        }
        await expect(async () => {
            await resolveTeam(hub, incomingEvent)
        }).rejects.toThrowError('retry me')
    })
})
