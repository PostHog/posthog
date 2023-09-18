import { PipelineEvent, Team } from '../../../../src/types'
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

let runner: any

beforeEach(() => {
    resetMetrics()
    runner = {
        nextStep: (...args: any[]) => args,
        hub: {
            teamManager: {
                getTeamByToken: jest.fn((token) => {
                    return token === teamTwoToken ? teamTwo : null
                }),
            },
        },
    }
})

describe('populateTeamDataStep()', () => {
    it('event with no token is not processed and the step returns null', async () => {
        const response = await populateTeamDataStep(runner, { ...pipelineEvent })
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
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, token: 'unknown' })
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

    it('event with a valid token gets assigned a team_id keeps its ip', async () => {
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, token: teamTwoToken })

        expect(response).toEqual({ ...pipelineEvent, token: teamTwoToken, team_id: 2, ip: '127.0.0.1' })
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([])
    })

    it('event with a valid token for a team with anonymize_ips=true keeps its ip', async () => {
        // NOTE: The IP is intentionally kept in `populateTeamDataStep` so that it is still
        // available for plugins. It is later removed by `prepareEventStep`.
        jest.mocked(runner.hub.teamManager.getTeamByToken).mockReturnValue({ ...teamTwo, anonymize_ips: true })
        const response = await populateTeamDataStep(runner, { ...pipelineEvent, token: teamTwoToken })

        expect(response).toEqual({ ...pipelineEvent, token: teamTwoToken, team_id: 2, ip: '127.0.0.1' })
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([])
    })

    it('event with a team_id value is returned unchanged', async () => {
        jest.mocked(runner.hub.teamManager.getTeamByToken).mockRejectedValueOnce(new Error('should not be called'))
        const input = { ...pipelineEvent, team_id: 43 }
        const response = await populateTeamDataStep(runner, input)
        expect(response).toEqual(input)
    })

    it('PG errors are propagated up to trigger retries', async () => {
        jest.mocked(runner.hub.teamManager.getTeamByToken).mockRejectedValueOnce(new Error('retry me'))
        await expect(async () => {
            await populateTeamDataStep(runner, { ...pipelineEvent, token: teamTwoToken })
        }).rejects.toThrowError('retry me')
    })
})
