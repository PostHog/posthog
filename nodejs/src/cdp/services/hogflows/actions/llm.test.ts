import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { createExampleHogFlowInvocation } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'

import { findActionById, findActionByType } from '../hogflow-utils'
import { LlmActionHandler, LlmStepTimeoutError } from './llm'

describe('action.llm', () => {
    let invocation: CyclotronJobInvocationHogFlow
    let action: Extract<HogFlowAction, { type: 'llm' }>
    let hogFlow: HogFlow
    let handler: LlmActionHandler
    let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>

    beforeEach(() => {
        const fixedTime = DateTime.fromObject({ year: 2025, month: 1, day: 1 }, { zone: 'UTC' })
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.toMillis())

        hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    llm: {
                        type: 'llm',
                        config: {
                            model: 'openai/gpt-4',
                            messages: [
                                {
                                    role: 'user',
                                    content: { value: 'Greet {{ person.properties.name }}', templating: 'liquid' },
                                },
                            ],
                            max_wait_duration: '5m',
                        },
                    },
                    next: {
                        type: 'delay',
                        config: { delay_duration: '1h' },
                    },
                },
                edges: [{ from: 'llm', to: 'next', type: 'continue' }],
            })
            .build()

        action = findActionByType(hogFlow, 'llm')!
        invocation = createExampleHogFlowInvocation(hogFlow)
        invocation.state.currentAction = { id: action.id, startedAtTimestamp: DateTime.utc().toMillis() }
        handler = new LlmActionHandler()
        result = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation)
    })

    const run = () => handler.execute({ invocation, action, result })

    it('on entry dispatches one request with the rendered prompt and parks until the backstop', async () => {
        const res = await run()

        // Parked, not advanced.
        expect(res.scheduledAt).toEqual(DateTime.utc().plus({ minutes: 5 }))
        expect(res.nextAction).toBeUndefined()
        expect(res.finished).toBeFalsy()

        // Dispatched exactly one request, with the prompt rendered against workflow state.
        expect(result.llmRequests).toHaveLength(1)
        const request = result.llmRequests![0]
        expect(request.jobId).toBe(invocation.id)
        expect(request.model).toBe('openai/gpt-4')
        expect(request.messages).toEqual([{ role: 'user', content: 'Greet John Doe' }])

        // The nonce is recorded on state so the executor can wake this exact attempt.
        expect(invocation.state.currentAction!.llmRequestId).toBe(request.nonce)
    })

    it('advances to the next step with the completion when the executor wakes it with a result', async () => {
        await run()
        // The executor wakes the job by writing the completion into state.
        invocation.state.currentAction!.llmResult = { text: 'Hello John', model: 'openai/gpt-4' }

        const res = await run()

        expect(res.nextAction).toEqual(findActionById(hogFlow, 'next'))
        expect(res.result).toEqual({ text: 'Hello John', parsed: undefined, model: 'openai/gpt-4' })
        // Result + nonce consumed so a stray later wake can't re-trigger the step.
        expect(invocation.state.currentAction!.llmResult).toBeUndefined()
        expect(invocation.state.currentAction!.llmRequestId).toBeUndefined()
    })

    it('throws (taking the on_error path) when the executor wakes it with a terminal error', async () => {
        await run()
        invocation.state.currentAction!.llmError = { message: 'gateway 500', retriable: true }

        await expect(run()).rejects.toThrow('LLM step failed: gateway 500')
    })

    it('throws a timeout when re-entered after dispatch with no result written (backstop fired)', async () => {
        await run() // dispatch + park; sets llmRequestId

        // No completion or error was written, so this dequeue is the scheduled backstop firing.
        await expect(run()).rejects.toThrow(LlmStepTimeoutError)
        // It must not silently advance or re-dispatch on timeout.
        expect(result.llmRequests).toHaveLength(1)
    })

    it('blocks the dispatch and throws when the rate limiter denies the call', async () => {
        handler = new LlmActionHandler({
            check: () => Promise.resolve({ allowed: false, reason: 'workflow exceeded 1 LLM calls/min' }),
        })

        await expect(run()).rejects.toThrow('rate limit')
        // The blocked call must never be dispatched.
        expect(result.llmRequests ?? []).toHaveLength(0)
    })

    describe('with an error branch wired', () => {
        beforeEach(() => {
            hogFlow = new FixtureHogFlowBuilder()
                .withWorkflow({
                    actions: {
                        llm: {
                            type: 'llm',
                            config: {
                                model: 'openai/gpt-4',
                                messages: [{ role: 'user', content: { value: 'hi', templating: 'liquid' } }],
                                max_wait_duration: '5m',
                            },
                        },
                        next: { type: 'delay', config: { delay_duration: '1h' } },
                        on_failure: { type: 'delay', config: { delay_duration: '1h' } },
                    },
                    edges: [
                        { from: 'llm', to: 'next', type: 'continue' },
                        { from: 'llm', to: 'on_failure', type: 'branch', index: 0 },
                    ],
                })
                .build()
            action = findActionByType(hogFlow, 'llm')!
            invocation = createExampleHogFlowInvocation(hogFlow)
            invocation.state.currentAction = { id: action.id, startedAtTimestamp: DateTime.utc().toMillis() }
            result = createInvocationResult<CyclotronJobInvocationHogFlow>(invocation)
        })

        it('routes a terminal error to the branch instead of throwing', async () => {
            await run()
            invocation.state.currentAction!.llmError = { message: 'gateway 500', retriable: true }

            const res = await run()
            expect(res.nextAction).toEqual(findActionById(hogFlow, 'on_failure'))
        })

        it('routes a timeout to the branch instead of throwing', async () => {
            await run()
            const res = await run() // backstop fired, no result

            expect(res.nextAction).toEqual(findActionById(hogFlow, 'on_failure'))
        })
    })
})
