import { parseJSON } from '~/common/utils/json-parse'

import { executeLlmRequest } from './llm-executor-core'
import { LlmGatewayClient, LlmGatewayError } from './llm-gateway.client'
import { LlmStepRequest } from './llm-step.types'

const REQUEST: LlmStepRequest = {
    jobId: 'job1',
    teamId: 1,
    hogFlowId: 'flow1',
    actionId: 'a1',
    nonce: 'n1',
    model: 'openai/gpt-4',
    messages: [{ role: 'user', content: 'hi' }],
}

// A fake pool that always returns the job parked at (a1, n1), so wakeParkedLlmJob resolves 'woken'
// and we can inspect what state got written.
function fakePool() {
    const updates: Buffer[] = []
    const client = {
        query: async (text: string, values?: any[]) => {
            if (text.trimStart().startsWith('SELECT')) {
                const state = Buffer.from(
                    JSON.stringify({
                        state: { event: {}, actionStepCount: 1, currentAction: { id: 'a1', llmRequestId: 'n1' } },
                    })
                )
                return { rows: [{ state, action_id: 'a1' }], rowCount: 1 }
            }
            if (text.trimStart().startsWith('UPDATE')) {
                updates.push(values![1] as Buffer)
            }
            return { rows: [], rowCount: 1 }
        },
        release: () => {},
    }
    return { pool: { connect: async () => client as any }, updates }
}

const noSleep = () => Promise.resolve()

describe('executeLlmRequest', () => {
    it('calls the gateway with the (jobId, actionId, nonce) idempotency key and wakes with the completion', async () => {
        const complete = jest.fn().mockResolvedValue({ text: 'answer' })
        const gatewayClient: LlmGatewayClient = { complete }
        const { pool, updates } = fakePool()

        const { outcome } = await executeLlmRequest({ request: REQUEST, gatewayClient, pool })

        expect(outcome).toBe('woken')
        expect(complete).toHaveBeenCalledTimes(1)
        expect(complete).toHaveBeenCalledWith(REQUEST, { idempotencyKey: 'job1:a1:n1' })
        const written = parseJSON(updates[0].toString('utf-8'))
        expect(written.state.currentAction.llmResult).toEqual({ text: 'answer' })
    })

    it('retries a retriable gateway failure and succeeds', async () => {
        const complete = jest
            .fn()
            .mockRejectedValueOnce(new LlmGatewayError('429', true, 429))
            .mockResolvedValueOnce({ text: 'answer' })
        const gatewayClient: LlmGatewayClient = { complete }
        const { pool } = fakePool()

        const { outcome } = await executeLlmRequest({ request: REQUEST, gatewayClient, pool, sleep: noSleep })

        expect(outcome).toBe('woken')
        expect(complete).toHaveBeenCalledTimes(2)
    })

    it('does not retry a non-retriable failure and wakes the job with the error', async () => {
        const complete = jest.fn().mockRejectedValue(new LlmGatewayError('bad request', false, 400))
        const gatewayClient: LlmGatewayClient = { complete }
        const { pool, updates } = fakePool()

        const { outcome, error } = await executeLlmRequest({ request: REQUEST, gatewayClient, pool, sleep: noSleep })

        expect(complete).toHaveBeenCalledTimes(1) // no retry
        expect(outcome).toBe('woken')
        expect(error).toEqual({ message: 'bad request', retriable: false })
        const written = parseJSON(updates[0].toString('utf-8'))
        expect(written.state.currentAction.llmError).toEqual({ message: 'bad request', retriable: false })
    })

    it('gives up after exhausting retries and wakes the job with the error', async () => {
        const complete = jest.fn().mockRejectedValue(new LlmGatewayError('provider down', true, 503))
        const gatewayClient: LlmGatewayClient = { complete }
        const { pool, updates } = fakePool()

        const { error } = await executeLlmRequest({
            request: REQUEST,
            gatewayClient,
            pool,
            maxAttempts: 2,
            sleep: noSleep,
        })

        expect(complete).toHaveBeenCalledTimes(2)
        expect(error?.message).toBe('provider down')
        const written = parseJSON(updates[0].toString('utf-8'))
        expect(written.state.currentAction.llmError.message).toBe('provider down')
    })
})
