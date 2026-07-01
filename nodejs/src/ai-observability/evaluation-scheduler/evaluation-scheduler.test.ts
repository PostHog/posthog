import { Message } from 'node-rdkafka'

import {
    createAiGenerationEvent,
    createEvaluation,
    createEvaluationCondition,
    createTagger,
} from '~/ai-observability/_tests/fixtures'
import { logger } from '~/common/utils/logger'

import {
    EvaluationMatcher,
    checkConditionMatch,
    checkRolloutPercentage,
    eachBatchEvaluationScheduler,
    extractTraceContext,
    filterAndParseMessages,
    groupEventsByTeam,
    unwrapOrLog,
} from './evaluation-scheduler'

jest.mock('~/ai-observability/services/temporal.service', () => {
    const actual = jest.requireActual('~/ai-observability/services/temporal.service')
    return {
        ...actual,
        TemporalService: jest.fn(),
    }
})
jest.mock('~/ai-observability/services/evaluation-manager.service')
jest.mock('~/cdp/utils/hog-exec')

describe('Evaluation Scheduler', () => {
    const teamId = 1

    afterEach(() => {
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
            expect(checkRolloutPercentage('event-1', 100)).toBe(true)
            expect(checkRolloutPercentage('event-2', 100)).toBe(true)
            expect(checkRolloutPercentage('any-event', 100)).toBe(true)
        })

        it('is deterministic for same event id', () => {
            const result1 = checkRolloutPercentage('event-123', 50)
            const result2 = checkRolloutPercentage('event-123', 50)
            expect(result1).toBe(result2)
        })

        it('excludes some events at 0% rollout', () => {
            expect(checkRolloutPercentage('event-1', 0)).toBe(false)
            expect(checkRolloutPercentage('event-2', 0)).toBe(false)
        })

        it('includes roughly correct percentage of events', () => {
            const testEventIds = Array.from({ length: 1000 }, (_, i) => `event-${i}`)
            const included = testEventIds.filter((eventId) => checkRolloutPercentage(eventId, 30))

            // Should be roughly 30%, allow 5% variance
            expect(included.length).toBeGreaterThan(250)
            expect(included.length).toBeLessThan(350)
        })
    })

    describe('checkConditionMatch', () => {
        let mockExecHog: jest.Mock

        beforeEach(() => {
            mockExecHog = require('~/cdp/utils/hog-exec').execHog as jest.Mock
        })

        it('passes person properties from event to bytecode execution globals', async () => {
            mockExecHog.mockResolvedValue({ execResult: { result: true } })

            const personProperties = { is_internal: true, plan: 'enterprise' }
            const eventProperties = { $ai_model: 'gpt-4' }
            const event = createAiGenerationEvent(teamId, {
                person_properties: JSON.stringify(personProperties),
                properties: JSON.stringify(eventProperties),
            })
            const condition = createEvaluationCondition({
                bytecode: ['_H', 1, 32, true],
                rollout_percentage: 100,
            })

            await checkConditionMatch(event, condition)

            expect(mockExecHog).toHaveBeenCalledWith(
                condition.bytecode,
                expect.objectContaining({
                    globals: expect.objectContaining({
                        event: '$ai_generation',
                        distinct_id: event.distinct_id,
                        person: { properties: personProperties },
                        properties: eventProperties,
                    }),
                })
            )
        })

        it('handles empty person properties gracefully', async () => {
            mockExecHog.mockResolvedValue({ execResult: { result: true } })

            const event = createAiGenerationEvent(teamId, {
                person_properties: '{}',
            })
            const condition = createEvaluationCondition({
                bytecode: ['_H', 1, 32, true],
                rollout_percentage: 100,
            })

            await checkConditionMatch(event, condition)

            expect(mockExecHog).toHaveBeenCalledWith(
                condition.bytecode,
                expect.objectContaining({
                    globals: expect.objectContaining({
                        person: { properties: {} },
                    }),
                })
            )
        })

        it('handles missing person properties gracefully', async () => {
            mockExecHog.mockResolvedValue({ execResult: { result: true } })

            const event = createAiGenerationEvent(teamId)
            // Simulate missing person_properties by setting to undefined
            delete (event as any).person_properties
            const condition = createEvaluationCondition({
                bytecode: ['_H', 1, 32, true],
                rollout_percentage: 100,
            })

            await checkConditionMatch(event, condition)

            expect(mockExecHog).toHaveBeenCalledWith(
                condition.bytecode,
                expect.objectContaining({
                    globals: expect.objectContaining({
                        person: { properties: {} },
                    }),
                })
            )
        })
    })

    describe('EvaluationMatcher', () => {
        let matcher: EvaluationMatcher
        let mockExecHog: jest.Mock

        beforeEach(() => {
            matcher = new EvaluationMatcher()
            mockExecHog = require('~/cdp/utils/hog-exec').execHog as jest.Mock
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
            const event = createAiGenerationEvent(teamId, { uuid: 'event-test-uuid' })
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [createEvaluationCondition({ rollout_percentage: 0, bytecode: ['_H', 1, 32, true] })],
            })

            const result = await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(result).toEqual({ matched: false, reason: 'filtered' })
        })

        it('passes person properties to bytecode execution', async () => {
            mockExecHog.mockResolvedValue({
                execResult: { result: true },
            })

            const personProperties = { is_internal: true, email: 'test@example.com' }
            const event = createAiGenerationEvent(teamId, {
                person_properties: JSON.stringify(personProperties),
            })
            const evaluation = createEvaluation({
                enabled: true,
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', rollout_percentage: 100, bytecode: ['_H', 1, 32, true] }),
                ],
            })

            await matcher.shouldTriggerEvaluation(event, evaluation)

            expect(mockExecHog).toHaveBeenCalledWith(
                ['_H', 1, 32, true],
                expect.objectContaining({
                    globals: expect.objectContaining({
                        person: {
                            properties: personProperties,
                        },
                    }),
                })
            )
        })

        it('matches taggers using the same Matchable contract as evaluations', async () => {
            mockExecHog.mockResolvedValue({ execResult: { result: true } })

            const event = createAiGenerationEvent(teamId)
            const tagger = createTagger({
                enabled: true,
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', rollout_percentage: 100, bytecode: ['_H', 1, 32, true] }),
                ],
            })

            const result = await matcher.shouldTriggerEvaluation(event, tagger)

            expect(result).toEqual({ matched: true, conditionId: 'cond-1' })
        })

        it('returns disabled for a disabled tagger without consulting bytecode', async () => {
            const event = createAiGenerationEvent(teamId)
            const tagger = createTagger({ enabled: false })

            const result = await matcher.shouldTriggerEvaluation(event, tagger)

            expect(result).toEqual({ matched: false, reason: 'disabled' })
            expect(mockExecHog).not.toHaveBeenCalled()
        })
    })

    describe('unwrapOrLog', () => {
        it('returns the value when the promise was fulfilled', () => {
            const result = unwrapOrLog(
                { status: 'fulfilled', value: { 1: ['a'], 2: ['b'] } } as PromiseSettledResult<
                    Record<string, string[]>
                >,
                'should not log'
            )

            expect(result).toEqual({ 1: ['a'], 2: ['b'] })
        })

        it('returns an empty object and logs when rejected', () => {
            const errorSpy = jest.spyOn(logger, 'error').mockImplementation(() => undefined)

            const result = unwrapOrLog(
                { status: 'rejected', reason: new Error('db down') } as PromiseSettledResult<Record<string, string[]>>,
                'fetch failed'
            )

            expect(result).toEqual({})
            expect(errorSpy).toHaveBeenCalledWith('fetch failed', { error: 'db down' })

            errorSpy.mockRestore()
        })

        it('coerces non-Error rejection reasons to string for the log payload', () => {
            const errorSpy = jest.spyOn(logger, 'error').mockImplementation(() => undefined)

            unwrapOrLog(
                { status: 'rejected', reason: 'plain string failure' } as PromiseSettledResult<
                    Record<string, string[]>
                >,
                'fetch failed'
            )

            expect(errorSpy).toHaveBeenCalledWith('fetch failed', { error: 'plain string failure' })

            errorSpy.mockRestore()
        })
    })

    describe('extractTraceContext', () => {
        it('extracts string trace and session ids', () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_trace_id: 'trace-1', $session_id: 'session-1' }),
            })

            expect(extractTraceContext(event)).toEqual({ traceId: 'trace-1', sessionId: 'session-1' })
        })

        it('coerces numeric trace ids to strings', () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_trace_id: 0 }),
            })

            expect(extractTraceContext(event)).toEqual({ traceId: '0', sessionId: null })
        })

        it('returns nulls for missing or empty ids', () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_trace_id: '', $ai_input: 'hi' }),
            })

            expect(extractTraceContext(event)).toEqual({ traceId: null, sessionId: null })
        })

        it('returns nulls on malformed properties JSON', () => {
            const event = createAiGenerationEvent(teamId, { properties: 'not json{' })

            expect(extractTraceContext(event)).toEqual({ traceId: null, sessionId: null })
        })
    })

    describe('EvaluationMatcher sampling key', () => {
        let mockExecHog: jest.Mock

        beforeEach(() => {
            mockExecHog = require('~/cdp/utils/hog-exec').execHog as jest.Mock
            mockExecHog.mockResolvedValue({ execResult: { result: true } })
        })

        it('samples on the provided key instead of the event uuid', async () => {
            const matcher = new EvaluationMatcher()
            const evaluation = createEvaluation({
                conditions: [createEvaluationCondition({ bytecode: ['_H', 1, 32, true], rollout_percentage: 50 })],
            })
            const keys = Array.from({ length: 100 }, (_, i) => `trace-${i}`)
            const includedKey = keys.find((key) => checkRolloutPercentage(key, 50))!
            const excludedKey = keys.find((key) => !checkRolloutPercentage(key, 50))!
            const event = createAiGenerationEvent(teamId)

            const includedResult = await matcher.shouldTriggerEvaluation(event, evaluation, includedKey)
            const excludedResult = await matcher.shouldTriggerEvaluation(event, evaluation, excludedKey)

            expect(includedResult.matched).toBe(true)
            expect(excludedResult.matched).toBe(false)
        })
    })

    describe('eachBatchEvaluationScheduler trace-target evaluations', () => {
        let mockExecHog: jest.Mock
        let evaluationManager: import('~/ai-observability/services/evaluation-manager.service').EvaluationManagerService
        let taggerManager: import('~/ai-observability/services/tagger-manager.service').TaggerManagerService
        let temporalService: import('~/ai-observability/services/temporal.service').TemporalService

        const messageFor = (event: ReturnType<typeof createAiGenerationEvent>): Message =>
            ({
                headers: [{ productTrack: Buffer.from('llma') }],
                value: Buffer.from(JSON.stringify(event)),
            }) as any

        beforeEach(() => {
            mockExecHog = require('~/cdp/utils/hog-exec').execHog as jest.Mock
            mockExecHog.mockResolvedValue({ execResult: { result: true } })

            evaluationManager = {
                getEvaluationsForTeams: jest.fn().mockResolvedValue({}),
            } as unknown as import('~/ai-observability/services/evaluation-manager.service').EvaluationManagerService
            taggerManager = {
                getTaggersForTeams: jest.fn().mockResolvedValue({}),
            } as unknown as import('~/ai-observability/services/tagger-manager.service').TaggerManagerService
            temporalService = {
                startEvaluationRunWorkflow: jest.fn().mockResolvedValue(undefined),
                startTraceEvaluationRunWorkflow: jest.fn().mockResolvedValue(undefined),
                startTaggerRunWorkflow: jest.fn().mockResolvedValue(undefined),
            } as unknown as import('~/ai-observability/services/temporal.service').TemporalService
        })

        it('dispatches the trace workflow with trace context and the config window', async () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_trace_id: 'trace-1', $session_id: 'session-1' }),
            })
            const evaluation = createEvaluation({
                team_id: teamId,
                target: 'trace',
                target_config: { window_seconds: 90 },
                conditions: [createEvaluationCondition({ bytecode: ['_H', 1, 32, true], rollout_percentage: 100 })],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService)

            expect(temporalService.startTraceEvaluationRunWorkflow).toHaveBeenCalledWith(
                evaluation.id,
                event,
                'trace-1',
                'session-1',
                90
            )
            expect(temporalService.startEvaluationRunWorkflow).not.toHaveBeenCalled()
        })

        it('falls back to the default window when target_config has none', async () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_trace_id: 'trace-1' }),
            })
            const evaluation = createEvaluation({
                team_id: teamId,
                target: 'trace',
                target_config: {},
                conditions: [createEvaluationCondition({ bytecode: ['_H', 1, 32, true], rollout_percentage: 100 })],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService)

            const call = (temporalService.startTraceEvaluationRunWorkflow as jest.Mock).mock.calls[0]
            expect(call[4]).toBe(30 * 60)
        })

        it('skips trace-target evaluations when the event carries no trace id', async () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_input: 'hi' }),
            })
            const evaluation = createEvaluation({
                team_id: teamId,
                target: 'trace',
                conditions: [createEvaluationCondition({ bytecode: ['_H', 1, 32, true], rollout_percentage: 100 })],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService)

            expect(temporalService.startTraceEvaluationRunWorkflow).not.toHaveBeenCalled()
            expect(temporalService.startEvaluationRunWorkflow).not.toHaveBeenCalled()
        })

        it('keeps dispatching the per-generation workflow for generation-target evaluations', async () => {
            const event = createAiGenerationEvent(teamId, {
                properties: JSON.stringify({ $ai_trace_id: 'trace-1' }),
            })
            const evaluation = createEvaluation({
                team_id: teamId,
                target: 'generation',
                conditions: [createEvaluationCondition({ bytecode: ['_H', 1, 32, true], rollout_percentage: 100 })],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService)

            expect(temporalService.startEvaluationRunWorkflow).toHaveBeenCalledWith(
                evaluation.id,
                event,
                evaluation.evaluation_type
            )
            expect(temporalService.startTraceEvaluationRunWorkflow).not.toHaveBeenCalled()
        })
    })

    describe('eachBatchEvaluationScheduler batching', () => {
        const noopEvaluationManager = {
            getEvaluationsForTeams: jest.fn().mockResolvedValue({}),
        } as unknown as import('~/ai-observability/services/evaluation-manager.service').EvaluationManagerService
        const noopTaggerManager = {
            getTaggersForTeams: jest.fn().mockResolvedValue({}),
        } as unknown as import('~/ai-observability/services/tagger-manager.service').TaggerManagerService
        const noopTemporal = {} as unknown as import('~/ai-observability/services/temporal.service').TemporalService

        beforeEach(() => {
            ;(noopEvaluationManager.getEvaluationsForTeams as jest.Mock).mockClear()
            ;(noopTaggerManager.getTaggersForTeams as jest.Mock).mockClear()
        })

        const messageFor = (teamIdForEvent: number): Message =>
            ({
                headers: [{ productTrack: Buffer.from('llma') }],
                value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamIdForEvent))),
            }) as any

        it('fetches definitions for every team in the batch', async () => {
            await eachBatchEvaluationScheduler(
                [messageFor(2), messageFor(7), messageFor(99)],
                noopEvaluationManager,
                noopTaggerManager,
                noopTemporal
            )

            expect(noopEvaluationManager.getEvaluationsForTeams).toHaveBeenCalledTimes(1)
            const teamsAsked = (noopEvaluationManager.getEvaluationsForTeams as jest.Mock).mock.calls[0][0] as number[]
            expect(teamsAsked.sort((a, b) => a - b)).toEqual([2, 7, 99])
        })

        it('skips Postgres entirely when the batch has no $ai_generation events', async () => {
            await eachBatchEvaluationScheduler([], noopEvaluationManager, noopTaggerManager, noopTemporal)

            expect(noopEvaluationManager.getEvaluationsForTeams).not.toHaveBeenCalled()
            expect(noopTaggerManager.getTaggersForTeams).not.toHaveBeenCalled()
        })
    })

    describe('eachBatchEvaluationScheduler provider key gate', () => {
        let mockExecHog: jest.Mock
        let evaluationManager: import('~/ai-observability/services/evaluation-manager.service').EvaluationManagerService
        let taggerManager: import('~/ai-observability/services/tagger-manager.service').TaggerManagerService
        let temporalService: import('~/ai-observability/services/temporal.service').TemporalService
        let providerKeyManager: import('~/ai-observability/services/provider-key-manager.service').ProviderKeyManagerService

        const messageFor = (event: ReturnType<typeof createAiGenerationEvent>): Message =>
            ({
                headers: [{ productTrack: Buffer.from('llma') }],
                value: Buffer.from(JSON.stringify(event)),
            }) as any

        beforeEach(() => {
            mockExecHog = require('~/cdp/utils/hog-exec').execHog as jest.Mock
            mockExecHog.mockResolvedValue({ execResult: { result: true } })

            evaluationManager = {
                getEvaluationsForTeams: jest.fn().mockResolvedValue({}),
            } as unknown as import('~/ai-observability/services/evaluation-manager.service').EvaluationManagerService
            taggerManager = {
                getTaggersForTeams: jest.fn().mockResolvedValue({}),
            } as unknown as import('~/ai-observability/services/tagger-manager.service').TaggerManagerService
            temporalService = {
                startEvaluationRunWorkflow: jest.fn().mockResolvedValue(undefined),
                startTaggerRunWorkflow: jest.fn().mockResolvedValue(undefined),
            } as unknown as import('~/ai-observability/services/temporal.service').TemporalService
            providerKeyManager = {
                getProviderKey: jest.fn().mockResolvedValue({ id: 'key-1', team_id: teamId, state: 'error' }),
            } as unknown as import('~/ai-observability/services/provider-key-manager.service').ProviderKeyManagerService
        })

        it('does not start evaluation workflows when the configured provider key is not ok', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                team_id: teamId,
                provider_key_id: 'key-1',
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', bytecode: ['_H', 1, 32, true], rollout_percentage: 100 }),
                ],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService, {
                enabled: true,
                providerKeyManager,
            })

            expect(providerKeyManager.getProviderKey).toHaveBeenCalledWith('key-1')
            expect(temporalService.startEvaluationRunWorkflow).not.toHaveBeenCalled()
        })

        it('still starts evaluation workflows for trial mode evaluations', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                team_id: teamId,
                provider_key_id: null,
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', bytecode: ['_H', 1, 32, true], rollout_percentage: 100 }),
                ],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService, {
                enabled: true,
                providerKeyManager,
            })

            expect(providerKeyManager.getProviderKey).not.toHaveBeenCalled()
            expect(temporalService.startEvaluationRunWorkflow).toHaveBeenCalledWith(
                evaluation.id,
                event,
                evaluation.evaluation_type
            )
        })

        it('does not provider-key gate sentiment evaluations', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                team_id: teamId,
                evaluation_type: 'sentiment',
                evaluation_config: { source: 'user_messages' },
                output_type: 'sentiment',
                output_config: {},
                provider_key_id: 'key-1',
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', bytecode: ['_H', 1, 32, true], rollout_percentage: 100 }),
                ],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService, {
                enabled: true,
                providerKeyManager,
            })

            expect(providerKeyManager.getProviderKey).not.toHaveBeenCalled()
            expect(temporalService.startEvaluationRunWorkflow).toHaveBeenCalledWith(
                evaluation.id,
                event,
                evaluation.evaluation_type
            )
        })

        it('does not start tagger workflows when the configured provider key is not ok', async () => {
            const event = createAiGenerationEvent(teamId)
            const tagger = createTagger({
                team_id: teamId,
                provider_key_id: 'key-1',
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', bytecode: ['_H', 1, 32, true], rollout_percentage: 100 }),
                ],
            })
            ;(taggerManager.getTaggersForTeams as jest.Mock).mockResolvedValue({ [teamId]: [tagger] })

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService, {
                enabled: true,
                providerKeyManager,
            })

            expect(providerKeyManager.getProviderKey).toHaveBeenCalledWith('key-1')
            expect(temporalService.startTaggerRunWorkflow).not.toHaveBeenCalled()
        })

        it('fails open when provider key lookup fails', async () => {
            const event = createAiGenerationEvent(teamId)
            const evaluation = createEvaluation({
                team_id: teamId,
                provider_key_id: 'key-1',
                conditions: [
                    createEvaluationCondition({ id: 'cond-1', bytecode: ['_H', 1, 32, true], rollout_percentage: 100 }),
                ],
            })
            ;(evaluationManager.getEvaluationsForTeams as jest.Mock).mockResolvedValue({ [teamId]: [evaluation] })
            ;(providerKeyManager.getProviderKey as jest.Mock).mockRejectedValue(new Error('db down'))

            await eachBatchEvaluationScheduler([messageFor(event)], evaluationManager, taggerManager, temporalService, {
                enabled: true,
                providerKeyManager,
            })

            expect(temporalService.startEvaluationRunWorkflow).toHaveBeenCalledWith(
                evaluation.id,
                event,
                evaluation.evaluation_type
            )
        })
    })
})
