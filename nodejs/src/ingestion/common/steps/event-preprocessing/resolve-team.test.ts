import { TeamManager } from '~/common/utils/team-manager'
import { drop, isOkResult, ok } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'
import { createTestMessage } from '~/tests/helpers/kafka-message'
import { getMetricValues, resetMetrics } from '~/tests/helpers/metrics'
import { createTestPipelineEvent } from '~/tests/helpers/pipeline-event'
import { createTestTeam } from '~/tests/helpers/team'
import { IncomingEvent } from '~/types'

import { applyVerifiedProperty, createResolveTeamStep } from './resolve-team'

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

    describe('$verified property', () => {
        const secretTeam = createTestTeam({
            id: 5,
            api_token: 'phc_public',
            secret_api_token: 'phs_primary',
            secret_api_token_backup: 'phs_backup',
        })

        beforeEach(() => {
            teamManager = {
                getTeamByToken: jest.fn(async (token) => {
                    if (['phc_public', 'phs_primary', 'phs_backup'].includes(token)) {
                        return Promise.resolve(secretTeam)
                    }
                    return Promise.resolve(token === teamTwoToken ? teamTwo : null)
                }),
                getTeam: jest.fn(),
            } as unknown as TeamManager
            step = createResolveTeamStep(teamManager)
        })

        const makeInput = (token: string, properties?: Record<string, any>) => ({
            message: createTestMessage(),
            headers: createTestEventHeaders({ token }),
            event: {
                event: { ...pipelineEvent, ...(properties !== undefined ? { properties } : {}) },
                message: createTestMessage(),
            } as IncomingEvent,
        })

        it.each([['phs_primary'], ['phs_backup']])(
            'event sent with secret token %s gets $verified: true',
            async (token) => {
                const response = await step(makeInput(token))
                expect(isOkResult(response)).toBe(true)
                const event = (response as any).value.event
                expect(event.properties).toEqual({ foo: 'bar', $verified: true })
                expect(await getMetricValues('ingestion_verified_property_total')).toEqual([
                    { labels: { action: 'verified' }, value: 1 },
                ])
            }
        )

        it.each([[true], [false], ['forged'], [1]])(
            'client-supplied $verified (%p) is stripped from public-token events',
            async (forgedValue) => {
                const response = await step(makeInput('phc_public', { foo: 'bar', $verified: forgedValue }))
                expect(isOkResult(response)).toBe(true)
                const event = (response as any).value.event
                expect(event.properties).toEqual({ foo: 'bar' })
                expect(await getMetricValues('ingestion_verified_property_total')).toEqual([
                    { labels: { action: 'stripped' }, value: 1 },
                ])
            }
        )

        it('client-supplied $verified is overwritten on secret-token events', async () => {
            const response = await step(makeInput('phs_primary', { foo: 'bar', $verified: 'forged' }))
            expect(isOkResult(response)).toBe(true)
            const event = (response as any).value.event
            expect(event.properties).toEqual({ foo: 'bar', $verified: true })
        })

        it('event without properties gets properties created with $verified', async () => {
            const input = {
                message: createTestMessage(),
                headers: createTestEventHeaders({ token: 'phs_primary' }),
                event: {
                    event: { ...pipelineEvent, properties: undefined },
                    message: createTestMessage(),
                } as IncomingEvent,
            }
            const response = await step(input)
            expect(isOkResult(response)).toBe(true)
            const event = (response as any).value.event
            expect(event.properties).toEqual({ $verified: true })
        })

        it('public token on a team without secret tokens leaves properties untouched', async () => {
            const response = await step(makeInput(teamTwoToken))
            expect(isOkResult(response)).toBe(true)
            const event = (response as any).value.event
            expect(event.properties).toEqual({ foo: 'bar' })
            expect(await getMetricValues('ingestion_verified_property_total')).toEqual([])
        })
    })
})

describe('applyVerifiedProperty()', () => {
    const team = createTestTeam({
        api_token: 'phc_public',
        secret_api_token: 'phs_primary',
        secret_api_token_backup: 'phs_backup',
    })
    const noSecretsTeam = createTestTeam({ api_token: 'phc_public' })

    it.each([
        ['phs_primary', { foo: 'bar' }, { foo: 'bar', $verified: true }],
        ['phs_backup', { foo: 'bar' }, { foo: 'bar', $verified: true }],
        ['phs_primary', { $verified: false }, { $verified: true }],
        ['phc_public', { foo: 'bar' }, { foo: 'bar' }],
        ['phc_public', { foo: 'bar', $verified: true }, { foo: 'bar' }],
        ['phc_public', { $verified: 'anything' }, {}],
    ])('token %s with properties %p results in %p', (token, properties, expected) => {
        const event = { ...createTestPipelineEvent({ properties }), team_id: team.id } as any
        applyVerifiedProperty(event, token, team)
        expect(event.properties).toEqual(expected)
    })

    it('does not verify against a team whose secret tokens are null', () => {
        const event = { ...createTestPipelineEvent({ properties: { $verified: true } }), team_id: 1 } as any
        applyVerifiedProperty(event, 'phc_public', noSecretsTeam)
        expect(event.properties).toEqual({})
    })

    it('undefined token strips a client-supplied $verified', () => {
        const event = { ...createTestPipelineEvent({ properties: { $verified: true } }), team_id: 1 } as any
        applyVerifiedProperty(event, undefined, team)
        expect(event.properties).toEqual({})
    })
})
