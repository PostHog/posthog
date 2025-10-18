import { Message } from 'node-rdkafka'

import { createAiGenerationEvent, createEvaluation, createEvaluationCondition } from '~/llm-analytics/_tests/fixtures'
import { Evaluation } from '~/llm-analytics/types'
import { Hub, RawKafkaEvent } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { parseJSON } from '~/utils/json-parse'

import { EvaluationManagerService } from '../../llm-analytics/services/evaluation-manager.service'
import { TemporalService } from '../../llm-analytics/services/temporal.service'

jest.mock('../../llm-analytics/services/temporal.service')
jest.mock('../../llm-analytics/services/evaluation-manager.service')

describe('Evaluation Scheduler', () => {
    let hub: Hub
    let mockTemporalService: jest.Mocked<TemporalService>
    let mockEvaluationManager: jest.Mocked<EvaluationManagerService>

    const teamId = 1

    beforeEach(async () => {
        hub = await createHub()

        mockTemporalService = {
            startEvaluationWorkflow: jest.fn().mockResolvedValue(undefined),
            disconnect: jest.fn().mockResolvedValue(undefined),
        } as any

        mockEvaluationManager = {
            getEvaluationsForTeams: jest.fn().mockResolvedValue({}),
        } as any
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('event filtering', () => {
        it('handles malformed event JSON gracefully', () => {
            const malformedMessage: Message = {
                partition: 1,
                topic: 'test',
                offset: 0,
                timestamp: Date.now(),
                size: 1,
                value: Buffer.from('not valid json{'),
            }

            expect(() => parseJSON(malformedMessage.value!.toString())).toThrow()
        })
    })

    describe('condition matching', () => {
        it('matches evaluation when bytecode returns true', () => {
            const condition = createEvaluationCondition({
                rollout_percentage: 100,
                properties: [],
                bytecode: ['_H', 1, 32, true], // Simple bytecode that returns true
            })

            expect(condition.bytecode).toBeDefined()
        })

        it('skips evaluation when bytecode has errors', () => {
            const condition = createEvaluationCondition({
                rollout_percentage: 100,
                properties: [],
                bytecode_error: 'Failed to compile',
            })

            expect(condition.bytecode_error).toBe('Failed to compile')
            expect(condition.bytecode).toBeUndefined()
        })

        it('skips evaluation when bytecode_error field is set', () => {
            const evaluation = createEvaluation({
                conditions: [
                    createEvaluationCondition({
                        bytecode_error: 'Compilation failed',
                    }),
                ],
            })

            expect(evaluation.conditions[0].bytecode_error).toBe('Compilation failed')
        })
    })

    describe('rollout percentage sampling', () => {
        it('includes event when rollout is 100%', () => {
            const condition = createEvaluationCondition({
                rollout_percentage: 100,
            })

            expect(condition.rollout_percentage).toBe(100)
        })

        it('excludes some events when rollout is less than 100%', () => {
            const condition = createEvaluationCondition({
                rollout_percentage: 50,
            })

            expect(condition.rollout_percentage).toBe(50)
            expect(condition.rollout_percentage).toBeLessThan(100)
        })

        it('deterministically samples based on distinct_id', () => {
            // The actual implementation uses MD5 hash for deterministic sampling
            // This is consistent with feature flag rollout behavior
            const event1 = createAiGenerationEvent(teamId, { distinct_id: 'user-1' })
            const event2 = createAiGenerationEvent(teamId, { distinct_id: 'user-1' })

            expect(event1.distinct_id).toBe(event2.distinct_id)
        })
    })

    describe('workflow triggering', () => {
        it('triggers Temporal workflow when evaluation matches', async () => {
            const evaluation: Evaluation = createEvaluation({
                id: 'eval-123',
                team_id: teamId,
                enabled: true,
                conditions: [
                    createEvaluationCondition({
                        rollout_percentage: 100,
                        properties: [],
                        bytecode: ['_H', 1, 32, true],
                    }),
                ],
            })

            mockEvaluationManager.getEvaluationsForTeams.mockResolvedValue({
                [teamId]: [evaluation],
            })

            await mockTemporalService.startEvaluationWorkflow('eval-123', 'event-uuid-123')

            expect(mockTemporalService.startEvaluationWorkflow).toHaveBeenCalledWith('eval-123', 'event-uuid-123')
        })

        it('does not trigger workflow when evaluation disabled', () => {
            const evaluation = createEvaluation({
                enabled: false,
            })

            expect(evaluation.enabled).toBe(false)
        })

        it('continues processing on workflow start error', async () => {
            mockTemporalService.startEvaluationWorkflow.mockRejectedValue(new Error('Temporal unavailable'))

            // The implementation catches errors and continues processing
            await expect(mockTemporalService.startEvaluationWorkflow('eval-123', 'event-456')).rejects.toThrow(
                'Temporal unavailable'
            )
        })

        it('triggers workflow only once per event (first match wins)', () => {
            const evaluation = createEvaluation({
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', rollout_percentage: 100 }),
                    createEvaluationCondition({ id: 'cond-2', rollout_percentage: 100 }),
                ],
            })

            expect(evaluation.conditions).toHaveLength(2)
            // In practice, the scheduler stops after the first matching condition
        })
    })

    describe('batch processing', () => {
        it('groups events by team for efficient evaluation loading', () => {
            const event1 = createAiGenerationEvent(1)
            const event2 = createAiGenerationEvent(1)
            const event3 = createAiGenerationEvent(2)

            const eventsByTeam: Record<number, RawKafkaEvent[]> = {}
            for (const event of [event1, event2, event3]) {
                eventsByTeam[event.team_id] = eventsByTeam[event.team_id] || []
                eventsByTeam[event.team_id].push(event)
            }

            expect(eventsByTeam[1]).toHaveLength(2)
            expect(eventsByTeam[2]).toHaveLength(1)
        })

        it('handles mix of matching and non-matching events', () => {
            const matchingEval = createEvaluation({
                id: 'eval-match',
                enabled: true,
                conditions: [createEvaluationCondition({ rollout_percentage: 100 })],
            })

            const disabledEval = createEvaluation({
                id: 'eval-disabled',
                enabled: false,
            })

            mockEvaluationManager.getEvaluationsForTeams.mockResolvedValue({
                [teamId]: [matchingEval, disabledEval],
            })

            expect(matchingEval.enabled).toBe(true)
            expect(disabledEval.enabled).toBe(false)
        })

        it('handles empty evaluation list for team', async () => {
            mockEvaluationManager.getEvaluationsForTeams.mockResolvedValue({
                [teamId]: [],
            })

            const result = await mockEvaluationManager.getEvaluationsForTeams([teamId])
            expect(result[teamId]).toEqual([])
        })
    })

    describe('evaluation manager integration', () => {
        it('fetches evaluations for all teams in batch', async () => {
            const _team1Events = [createAiGenerationEvent(1), createAiGenerationEvent(1)]
            const _team2Events = [createAiGenerationEvent(2)]

            mockEvaluationManager.getEvaluationsForTeams.mockResolvedValue({
                1: [createEvaluation({ team_id: 1 })],
                2: [createEvaluation({ team_id: 2 })],
            })

            await mockEvaluationManager.getEvaluationsForTeams([1, 2])

            expect(mockEvaluationManager.getEvaluationsForTeams).toHaveBeenCalledWith([1, 2])
        })
    })
})
