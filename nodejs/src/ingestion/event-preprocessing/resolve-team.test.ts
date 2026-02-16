import { TeamManager } from '~/utils/team-manager'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { getMetricValues, resetMetrics } from '../../../tests/helpers/metrics'
import { createTestPipelineEvent } from '../../../tests/helpers/pipeline-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { IncomingEvent } from '../../types'
import { drop, ok } from '../pipelines/results'
import { createResolveTeamStep } from './resolve-team'

const pipelineEvent = createTestPipelineEvent({
    event: '$pageview',
    properties: { foo: 'bar' },
    timestamp: '2020-02-23T02:15:00Z',
    now: '2020-02-23T02:15:00Z',
    distinct_id: 'my_id',
})

const teamTwo = createTestTeam({
    id: 2,
    uuid: 'af95d312-1a0a-4208-b80f-562ddafc9bcd',
    organization_id: '66f3f7bf-44e2-45dd-9901-5dbd93744e3a',
    name: 'testTeam',
    api_token: 'token',
    slack_incoming_webhook: '',
    session_recording_opt_in: false,
})

const teamTwoToken = 'token'

let teamManager: TeamManager
let step: ReturnType<typeof createResolveTeamStep>

beforeEach(() => {
    resetMetrics()
    teamManager = {
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

    step = createResolveTeamStep(teamManager)
})

describe('createResolveTeamStep()', () => {
    it('event with no token is not processed and the step returns drop', async () => {
        const input = {
            message: createTestMessage(),
            headers: createTestEventHeaders(),
            event: { event: { ...pipelineEvent }, message: createTestMessage() } as IncomingEvent,
        }
        const response = await step(input)
        expect(response).toEqual(drop('no_token'))
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

    it('event with an invalid token is not processed and the step returns drop', async () => {
        const input = {
            message: createTestMessage(),
            headers: createTestEventHeaders({ token: 'unknown' }),
            event: { event: { ...pipelineEvent }, message: createTestMessage() } as IncomingEvent,
        }
        const response = await step(input)
        expect(response).toEqual(drop('invalid_token'))
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

    it('event with a valid token replaces event with PluginEvent and adds team', async () => {
        const input = {
            message: createTestMessage(),
            headers: createTestEventHeaders({ token: teamTwoToken }),
            event: { event: { ...pipelineEvent }, message: createTestMessage() } as IncomingEvent,
        }
        const response = await step(input)
        expect(response).toEqual(
            ok({
                ...input,
                event: { ...pipelineEvent, team_id: teamTwo.id },
                team: teamTwo,
            })
        )
        expect(teamManager.getTeamByToken).toHaveBeenCalledWith(teamTwoToken)
        expect(teamManager.getTeam).not.toHaveBeenCalled()
    })

    it('event with team_id but no token is dropped', async () => {
        const input = {
            message: createTestMessage(),
            headers: createTestEventHeaders(),
            event: { event: { ...pipelineEvent, team_id: 3 }, message: createTestMessage() } as IncomingEvent,
        }
        const response = await step(input)
        expect(response).toEqual(drop('no_token'))
        expect(await getMetricValues('ingestion_event_dropped_total')).toEqual([
            {
                labels: {
                    drop_cause: 'no_token',
                    event_type: 'analytics',
                },
                value: 1,
            },
        ])
        expect(teamManager.getTeam).not.toHaveBeenCalled()
        expect(teamManager.getTeamByToken).not.toHaveBeenCalled()
    })

    it('event with both team_id and token uses token for team resolution', async () => {
        const input = {
            message: createTestMessage(),
            headers: createTestEventHeaders({ token: teamTwoToken }),
            event: {
                event: { ...pipelineEvent, team_id: 3 },
                message: createTestMessage(),
            } as IncomingEvent,
        }
        const response = await step(input)
        expect(response).toEqual(
            ok({
                ...input,
                event: { ...pipelineEvent, team_id: teamTwo.id },
                team: teamTwo,
            })
        )
        expect(teamManager.getTeamByToken).toHaveBeenCalledWith(teamTwoToken)
        expect(teamManager.getTeam).not.toHaveBeenCalled()
    })

    it('PG errors are propagated up to trigger retries', async () => {
        jest.mocked(teamManager.getTeamByToken).mockRejectedValueOnce(new Error('retry me'))
        const input = {
            message: createTestMessage(),
            headers: createTestEventHeaders({ token: teamTwoToken }),
            event: { event: { ...pipelineEvent }, message: createTestMessage() } as IncomingEvent,
        }
        await expect(async () => {
            await step(input)
        }).rejects.toThrow('retry me')
    })
})
