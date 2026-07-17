import { parseJSON } from '~/common/utils/json-parse'

import { applyLlmOutcomeToState, wakeParkedLlmJob } from './llm-wake'

// Builds the cyclotron_jobs.state bytea for a job parked at an LLM step: the serialized blob is
// { state: HogFlowInvocationContext, ... }, matching job-queue-postgres-v2's serializeState.
function parkedStateBuffer(args: { actionId: string; nonce: string; extra?: Record<string, unknown> }): Buffer {
    return Buffer.from(
        JSON.stringify({
            state: {
                event: {},
                actionStepCount: 1,
                currentAction: { id: args.actionId, startedAtTimestamp: 0, llmRequestId: args.nonce },
            },
            ...args.extra,
        })
    )
}

// A fake pg client/pool that records queries and returns canned SELECT rows.
function fakePool(selectRows: { state: Buffer | null; action_id: string | null }[]) {
    const queries: { text: string; values: any[] }[] = []
    const client = {
        query: async (text: string, values?: any[]) => {
            queries.push({ text, values: values ?? [] })
            if (text.trimStart().startsWith('SELECT')) {
                return { rows: selectRows, rowCount: selectRows.length }
            }
            return { rows: [], rowCount: 1 }
        },
        release: () => {},
    }
    return { pool: { connect: async () => client as any }, queries }
}

describe('llm-wake', () => {
    describe('applyLlmOutcomeToState', () => {
        it('writes the completion into currentAction and preserves the rest of the blob', () => {
            const buffer = parkedStateBuffer({ actionId: 'a1', nonce: 'n1', extra: { queueParameters: { foo: 1 } } })

            const out = applyLlmOutcomeToState(buffer, { nonce: 'n1', completion: { text: 'hi' } })

            expect(out).not.toBeNull()
            const parsed = parseJSON(out!.toString('utf-8'))
            expect(parsed.state.currentAction.llmResult).toEqual({ text: 'hi' })
            // Unrelated fields survive the round-trip.
            expect(parsed.queueParameters).toEqual({ foo: 1 })
            expect(parsed.state.actionStepCount).toBe(1)
        })

        it('drops a completion whose nonce no longer matches the parked attempt', () => {
            const buffer = parkedStateBuffer({ actionId: 'a1', nonce: 'n1' })

            // A redelivered / superseded completion carrying the old nonce must not wake a re-dispatch.
            expect(applyLlmOutcomeToState(buffer, { nonce: 'stale', completion: { text: 'hi' } })).toBeNull()
        })

        it('returns null when the job carries no current action', () => {
            const buffer = Buffer.from(JSON.stringify({ state: { event: {}, actionStepCount: 0 } }))
            expect(applyLlmOutcomeToState(buffer, { nonce: 'n1', completion: { text: 'hi' } })).toBeNull()
        })
    })

    describe('wakeParkedLlmJob', () => {
        it('wakes an available job whose step and nonce match, issuing scheduled = NOW()', async () => {
            const { pool, queries } = fakePool([
                { state: parkedStateBuffer({ actionId: 'a1', nonce: 'n1' }), action_id: 'a1' },
            ])

            const outcome = await wakeParkedLlmJob(pool, {
                jobId: 'job1',
                actionId: 'a1',
                nonce: 'n1',
                completion: { text: 'done' },
            })

            expect(outcome).toBe('woken')
            const update = queries.find((q) => q.text.includes('UPDATE cyclotron_jobs'))
            expect(update).toBeDefined()
            expect(update!.text).toContain('scheduled = NOW()')
            // The written state carries the completion.
            const writtenState = parseJSON((update!.values[1] as Buffer).toString('utf-8'))
            expect(writtenState.state.currentAction.llmResult).toEqual({ text: 'done' })
            expect(queries.some((q) => q.text.includes('COMMIT'))).toBe(true)
        })

        it('reports missed and issues no UPDATE when no available row exists (timeout won the race)', async () => {
            const { pool, queries } = fakePool([])

            const outcome = await wakeParkedLlmJob(pool, {
                jobId: 'job1',
                actionId: 'a1',
                nonce: 'n1',
                completion: { text: 'done' },
            })

            expect(outcome).toBe('missed')
            expect(queries.some((q) => q.text.includes('UPDATE cyclotron_jobs'))).toBe(false)
        })

        it('reports stale and issues no UPDATE when the job has advanced to a different step', async () => {
            const { pool, queries } = fakePool([
                { state: parkedStateBuffer({ actionId: 'a1', nonce: 'n1' }), action_id: 'a2' },
            ])

            const outcome = await wakeParkedLlmJob(pool, {
                jobId: 'job1',
                actionId: 'a1',
                nonce: 'n1',
                completion: { text: 'done' },
            })

            expect(outcome).toBe('stale')
            expect(queries.some((q) => q.text.includes('UPDATE cyclotron_jobs'))).toBe(false)
        })
    })
})
