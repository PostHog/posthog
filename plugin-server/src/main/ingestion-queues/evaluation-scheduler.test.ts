import { Message } from 'node-rdkafka'

import { createAiGenerationEvent, createEvaluation, createEvaluationCondition } from '~/llm-analytics/_tests/fixtures'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import {
    EvaluationMatcher,
    checkRolloutPercentage,
    filterAndParseMessages,
    groupEventsByTeam,
} from './evaluation-scheduler'

jest.mock('../../llm-analytics/services/temporal.service')
jest.mock('../../llm-analytics/services/evaluation-manager.service')
jest.mock('../../cdp/utils/hog-exec')

describe('Evaluation Scheduler', () => {
    let hub: Hub

    const teamId = 1

    beforeEach(async () => {
        hub = await createHub()
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    describe('filterAndParseMessages', () => {
        it('filters messages by productTrack header and parses JSON', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('general') }],
                    value: Buffer.from(JSON.stringify({ event: '$pageview', team_id: teamId })),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(2)
            result.forEach((event) => expect(event.event).toContain('$ai'))
        })

        it('handles malformed JSON gracefully', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from('invalid json{'),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(1)
        })

        it('filters out messages without llma header', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('general') }],
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                } as any,
                {
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(0)
        })
    })

    describe('groupEventsByTeam', () => {
        it('groups events by team_id', () => {
            const events = [
                createAiGenerationEvent(1),
                createAiGenerationEvent(1),
                createAiGenerationEvent(2),
                createAiGenerationEvent(3),
                createAiGenerationEvent(1),
            ]

            const grouped = groupEventsByTeam(events)

            expect(grouped.size).toBe(3)
            expect(grouped.get(1)).toHaveLength(3)
            expect(grouped.get(2)).toHaveLength(1)
            expect(grouped.get(3)).toHaveLength(1)
        })

        it('handles empty array', () => {
            const grouped = groupEventsByTeam([])
            expect(grouped.size).toBe(0)
        })
    })

    describe('checkRolloutPercentage', () => {
        it('always includes when rollout is 100%', () => {
            expect(checkRolloutPercentage('user-1', 100)).toBe(true)
            expect(checkRolloutPercentage('user-2', 100)).toBe(true)
            expect(checkRolloutPercentage('any-user', 100)).toBe(true)
        })

        it('is deterministic for same distinct_id', () => {
            const result1 = checkRolloutPercentage('user-123', 50)
            const result2 = checkRolloutPercentage('user-123', 50)
            expect(result1).toBe(result2)
        })

        it('excludes some users at 0% rollout', () => {
            expect(checkRolloutPercentage('user-1', 0)).toBe(false)
            expect(checkRolloutPercentage('user-2', 0)).toBe(false)
        })

        it('includes roughly correct percentage of users', () => {
            const testUsers = Array.from({ length: 1000 }, (_, i) => `user-${i}`)
            const included = testUsers.filter((user) => checkRolloutPercentage(user, 30))

            // Should be roughly 30%, allow 5% variance
            expect(included.length).toBeGreaterThan(250)
            expect(included.length).toBeLessThan(350)
        })
    })

    describe('EvaluationMatcher', () => {
        let matcher: EvaluationMatcher
        let mockExecHog: jest.Mock

        beforeEach(() => {
            matcher = new EvaluationMatcher()
            mockExecHog = require('../../cdp/utils/hog-exec').execHog as jest.Mock
        })

        it('returns disabled when evaluation is not enabled', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({ enabled: false })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: false, reason: 'disabled' })
        })

        it('returns no_conditions when evaluation has no conditions', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({ enabled: true, conditions: [] })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: false, reason: 'no_conditions' })
        })

        it('returns filtered when bytecode returns false', async () => {
            mockExecHog.mockResolvedValue({
                execResult: { result: false },
            })

            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [createEvaluationCondition({ rollout_percentage: 100, bytecode: ['_H', 1, 32, false] })],
            })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: false, reason: 'filtered' })
        })

        it('returns filtered when bytecode has error', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [createEvaluationCondition({ rollout_percentage: 100, bytecode_error: 'Failed' })],
            })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: false, reason: 'filtered' })
        })

        it('returns matched when condition matches and user in rollout', async () => {
            mockExecHog.mockResolvedValue({
                execResult: { result: true },
            })

            const event = createAiGenerationEvent(teamId, { distinct_id: 'user-1' })
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', rollout_percentage: 100, bytecode: ['_H', 1, 32, true] }),
                ],
            })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: true, conditionId: 'cond-1' })
        })

        it('tries multiple conditions until one matches', async () => {
            mockExecHog
                .mockResolvedValueOnce({ execResult: { result: false } })
                .mockResolvedValueOnce({ execResult: { result: true } })

            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [
                    createEvaluationCondition({
                        id: 'cond-1',
                        rollout_percentage: 100,
                        bytecode: ['_H', 1, 32, false],
                    }),
                    createEvaluationCondition({ id: 'cond-2', rollout_percentage: 100, bytecode: ['_H', 1, 32, true] }),
                ],
            })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: true, conditionId: 'cond-2' })
        })

        it('respects rollout percentage', async () => {
            mockExecHog.mockResolvedValue({
                execResult: { result: true },
            })

            // Test with 0% rollout - should never match due to sampling
            const event = createAiGenerationEvent(teamId, { distinct_id: 'user-test' })
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [createEvaluationCondition({ rollout_percentage: 0, bytecode: ['_H', 1, 32, true] })],
            })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: false, reason: 'filtered' })
        })
    })
})
