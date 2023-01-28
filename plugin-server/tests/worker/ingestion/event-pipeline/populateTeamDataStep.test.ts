import { PipelineEvent, Team } from '../../../../src/types'
import { UUIDT } from '../../../../src/utils/utils'
import { populateTeamDataStep } from '../../../../src/worker/ingestion/event-pipeline/populateTeamDataStep'

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

const { token, ...defaultResultEvent } = pipelineEvent

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
    runner = {
        nextStep: (...args: any[]) => args,
        hub: {
            teamManager: {
                getTeamByToken: jest.fn(() => team),
            },
        },
    }
})

describe('populateTeamDataStep()', () => {
    it('event with no token is not processed and the step returns null', async () => {
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, team_id: undefined, token: undefined })

        expect(response).toEqual(null)
    })

    it('event with a valid token gets assigned a team_id keeps its ip', async () => {
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, team_id: undefined })

        expect(response).toEqual({ ...defaultResultEvent, team_id: 2, ip: '127.0.0.1' })
    })

    it('event with a valid token for a team with anonymize_ips=true gets its ip set to null', async () => {
        jest.mocked(runner.hub.teamManager.getTeamByToken).mockReturnValue({ ...team, anonymize_ips: true })
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, team_id: undefined })

        expect(response).toEqual({ ...defaultResultEvent, team_id: 2, ip: null })
    })
})
