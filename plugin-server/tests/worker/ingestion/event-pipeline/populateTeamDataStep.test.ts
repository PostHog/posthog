import { PipelineEvent, Team } from '../../../../src/types'
import { UUIDT } from '../../../../src/utils/utils'
import { populateTeamDataStep } from '../../../../src/worker/ingestion/event-pipeline/1-populateTeamDataStep'
import { TeamManager } from '../../../../src/worker/ingestion/team-manager'

const pipelineEvent: PipelineEvent = {
    event: '$pageview',
    properties: { foo: 'bar' },
    timestamp: '2020-02-23T02:15:00Z',
    now: '2020-02-23T02:15:00Z',
    team_id: 2,
    distinct_id: 'my_id',
    ip: '127.0.0.1',
    site_url: 'https://example.com',
    uuid: new UUIDT().toString(),
    token: 'token',
}

const team: Team = {
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

let runner: any

beforeEach(() => {
    const db = { fetchTeamFromToken: jest.fn().mockResolvedValue(team) }

    runner = {
        nextStep: (...args: any[]) => args,
        hub: {
            db,
            eventsProcessor: {},
            graphileWorker: {
                enqueue: jest.fn(),
            },
            kafkaProducer: {
                queueMessage: jest.fn(),
            },
            teamManager: new TeamManager(db as any, {} as any),
        },
    }
})

describe('populateTeamDataStep()', () => {
    it('event already has team_id', async () => {
        const response = await populateTeamDataStep(runner, pipelineEvent)

        expect(response).toEqual(['emitToBufferStep', pipelineEvent])
    })
    it('event has no team_id and no token', async () => {
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, team_id: undefined, token: undefined })

        expect(response).toEqual(null)
    })

    it('event already has team_id', async () => {
        const response = await populateTeamDataStep(runner, pipelineEvent)

        expect(response).toEqual(['emitToBufferStep', pipelineEvent])
    })

    it('event has no team_id but has a token', async () => {
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, team_id: undefined })

        expect(response).toEqual(['emitToBufferStep', { ...pipelineEvent, team_id: 2, ip: '127.0.0.1' }])
    })

    it('team has anonymize_ips set', async () => {
        runner.hub.db.fetchTeamFromToken = jest.fn().mockResolvedValue({ ...team, anonymize_ips: true })

        const response = await populateTeamDataStep(runner, { ...pipelineEvent, team_id: undefined })

        expect(response).toEqual(['emitToBufferStep', { ...pipelineEvent, team_id: 2, ip: null }])
    })
})
