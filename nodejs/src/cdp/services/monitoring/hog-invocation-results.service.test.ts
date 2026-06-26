import { DateTime } from 'luxon'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { createExampleInvocation } from '../../_tests/fixtures'
import { CdpOutput } from '../../cdp-services'
import {
    HogInvocationResultRow,
    HogInvocationResultsService,
    decodeInvocationGlobals,
} from './hog-invocation-results.service'

const buildOutputsMock = (): jest.Mocked<IngestionOutputs<CdpOutput>> => {
    return {
        produce: jest.fn().mockResolvedValue(undefined),
    } as unknown as jest.Mocked<IngestionOutputs<CdpOutput>>
}

const parseProducedRows = (outputs: jest.Mocked<IngestionOutputs<CdpOutput>>): HogInvocationResultRow[] => {
    return outputs.produce.mock.calls.map((call) => {
        const arg = call[1] as { key: Buffer | null; value: Buffer | null }
        return parseJSON(arg.value!.toString('utf8')) as HogInvocationResultRow
    })
}

describe('HogInvocationResultsService', () => {
    let outputs: jest.Mocked<IngestionOutputs<CdpOutput>>
    let service: HogInvocationResultsService

    beforeEach(() => {
        outputs = buildOutputsMock()
        service = new HogInvocationResultsService(outputs, { HOG_INVOCATION_RESULTS_ENABLED: true })
    })

    describe('feature flag', () => {
        it('produces nothing when HOG_INVOCATION_RESULTS_ENABLED is false', async () => {
            service = new HogInvocationResultsService(outputs, { HOG_INVOCATION_RESULTS_ENABLED: false })

            const invocation = createExampleInvocation()
            service.queueLifecycleRow(invocation, 'running')
            service.queueInvocationResults([
                {
                    invocation,
                    finished: true,
                    error: undefined,
                    logs: [],
                    metrics: [],
                    capturedPostHogEvents: [],
                    warehouseWebhookPayloads: [],
                } as any,
            ])

            await service.flush()
            expect(outputs.produce).not.toHaveBeenCalled()
        })
    })

    describe('queueLifecycleRow', () => {
        it('writes a status=running row with start timing and no error fields', async () => {
            const invocation = createExampleInvocation()
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows).toHaveLength(1)
            const row = rows[0]
            expect(row.status).toBe('running')
            expect(row.function_kind).toBe('hog_function')
            expect(row.team_id).toBe(invocation.teamId)
            expect(row.function_id).toBe(invocation.functionId)
            expect(row.invocation_id).toBe(invocation.id)
            expect(row.is_retry).toBe(0)
            expect(row.started_at).not.toBeNull()
            expect(row.finished_at).toBeNull()
            expect(row.error_kind).toBe('')
            expect(row.error_message).toBe('')
        })

        it('strips inputs from invocation_globals — secrets must not be persisted', async () => {
            const invocation = createExampleInvocation(
                { id: 'fn-1', team_id: 1 },
                {
                    inputs: {
                        api_key: 'sk-super-secret',
                        nested: { token: 'abc123' },
                    } as any,
                }
            )
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows).toHaveLength(1)
            const globals = (await decodeInvocationGlobals(rows[0].invocation_globals)) as Record<string, any>

            // The event context we care about is preserved.
            expect(globals.event?.uuid).toBeDefined()
            expect(globals.project?.id).toBeDefined()
            // But `inputs` is gone entirely.
            expect(globals).not.toHaveProperty('inputs')
            // And the decoded payload does not mention the secret anywhere
            // (catches the case where a future schema change moves inputs
            // under a different key without us noticing).
            const decoded = JSON.stringify(globals)
            expect(decoded).not.toContain('sk-super-secret')
            expect(decoded).not.toContain('abc123')
        })

        it('strips groups and person from invocation_globals — rebuilt downstream on rerun', async () => {
            const invocation = createExampleInvocation({}, {
                groups: {
                    organization: {
                        id: 'org-1',
                        type: 'organization',
                        index: 0,
                        url: 'http://localhost',
                        properties: { plan: 'enterprise', seats: 500 },
                    },
                },
            } as any)
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            const globals = (await decodeInvocationGlobals(rows[0].invocation_globals)) as Record<string, any>
            expect(globals).not.toHaveProperty('groups')
            expect(globals).not.toHaveProperty('person')
            // The event — the rerun trigger — is kept.
            expect(globals.event?.uuid).toBeDefined()
            expect(globals.project?.id).toBeDefined()
        })

        it('marks is_retry=1 and attempts=N when state.rerunAttempts is set', async () => {
            const invocation = createExampleInvocation()
            invocation.state.rerunAttempts = 1
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows[0].is_retry).toBe(1)
            expect(rows[0].attempts).toBe(1)
        })

        it('leaves is_retry=0 and attempts=0 when state.rerunAttempts is unset (original run)', async () => {
            const invocation = createExampleInvocation()
            // Fetch-retry counter is bumped by the executor — it must NOT bleed
            // into the lifecycle row's `attempts`/`is_retry` fields.
            invocation.state.attempts = 3
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows[0].is_retry).toBe(0)
            expect(rows[0].attempts).toBe(0)
        })

        it('extracts event_uuid, distinct_id, and person_id into promoted columns', async () => {
            const invocation = createExampleInvocation({}, {
                event: {
                    uuid: 'event-uuid-123',
                    event: 'test',
                    elements_chain: '',
                    distinct_id: 'distinct-456',
                    url: 'http://localhost',
                    properties: {},
                    timestamp: '2026-05-01T00:00:00Z',
                },
                person: {
                    id: 'person-789',
                    name: 'x',
                    url: 'http://localhost',
                    properties: {},
                },
            } as any)
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows[0].event_uuid).toBe('event-uuid-123')
            expect(rows[0].distinct_id).toBe('distinct-456')
            expect(rows[0].person_id).toBe('person-789')
        })
    })

    describe('queueInvocationResults', () => {
        it('writes status=succeeded on a result with no error', async () => {
            const invocation = createExampleInvocation()
            service.queueInvocationResults([
                {
                    invocation,
                    finished: true,
                    error: undefined,
                    logs: [],
                    metrics: [],
                    capturedPostHogEvents: [],
                    warehouseWebhookPayloads: [],
                } as any,
            ])
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows).toHaveLength(1)
            expect(rows[0].status).toBe('succeeded')
            expect(rows[0].error_kind).toBe('')
        })

        it('writes status=failed and classifies the error kind', async () => {
            const invocation = createExampleInvocation()
            service.queueInvocationResults([
                {
                    invocation,
                    finished: true,
                    error: new Error('Request timed out after 30s'),
                    logs: [],
                    metrics: [],
                    capturedPostHogEvents: [],
                    warehouseWebhookPayloads: [],
                } as any,
            ])
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows).toHaveLength(1)
            expect(rows[0].status).toBe('failed')
            expect(rows[0].error_kind).toBe('timeout')
            expect(rows[0].error_message).toContain('timed out')
        })

        it('produces no row for an in-flight result that has not finished and has no error', async () => {
            const invocation = createExampleInvocation()
            service.queueInvocationResults([
                {
                    invocation,
                    finished: false,
                    error: undefined,
                    logs: [],
                    metrics: [],
                    capturedPostHogEvents: [],
                    warehouseWebhookPayloads: [],
                } as any,
            ])
            await service.flush()

            expect(outputs.produce).not.toHaveBeenCalled()
        })
    })

    describe('flush', () => {
        it('uses the invocation_id as the Kafka partition key', async () => {
            const invocation = createExampleInvocation({ id: 'fn-2' })
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const arg = outputs.produce.mock.calls[0][1] as { key: Buffer | null; value: Buffer | null }
            expect(arg.key?.toString('utf8')).toBe(invocation.id)
        })

        it('clears the queue after flush so a second flush is a no-op', async () => {
            const invocation = createExampleInvocation()
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()
            await service.flush()
            expect(outputs.produce).toHaveBeenCalledTimes(1)
        })
    })

    describe('version monotonicity', () => {
        it('produces strictly increasing version values across successive rows for the same invocation', async () => {
            const invocation = createExampleInvocation()
            service.queueLifecycleRow(invocation, 'running')
            // Tick by 1 ms — version is now64(6) in microseconds.
            await new Promise((r) => setTimeout(r, 2))
            service.queueLifecycleRow(invocation, 'succeeded')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows).toHaveLength(2)
            expect(BigInt(rows[1].version)).toBeGreaterThan(BigInt(rows[0].version))
        })
    })

    describe('invocation_globals compression', () => {
        it('produces invocation_globals as a compressed blob that round-trips back to the event', async () => {
            const invocation = createExampleInvocation({}, {
                event: {
                    uuid: 'event-uuid-rt',
                    event: '$pageview',
                    elements_chain: '',
                    distinct_id: 'distinct-rt',
                    url: 'http://localhost',
                    properties: { $current_url: 'https://posthog.com', big: 'x'.repeat(5000) },
                    timestamp: '2026-05-01T00:00:00Z',
                },
            } as any)
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            const stored = rows[0].invocation_globals
            // On the wire the field is a base64 blob — never raw JSON.
            expect(stored.startsWith('{')).toBe(false)
            // A repetitive 5KB event compresses well below its raw size.
            expect(stored.length).toBeLessThan(JSON.stringify(invocation.state.globals.event).length)
            // And it decodes back to the original event payload intact.
            const globals = (await decodeInvocationGlobals(stored)) as Record<string, any>
            expect(globals.event).toEqual(invocation.state.globals.event)
        })

        it('decodes legacy uncompressed (raw JSON) rows unchanged', async () => {
            const legacy = JSON.stringify({ event: { uuid: 'legacy-uuid' }, project: { id: 7 } })
            expect(await decodeInvocationGlobals(legacy)).toEqual({
                event: { uuid: 'legacy-uuid' },
                project: { id: 7 },
            })
        })
    })

    describe('first_scheduled_at', () => {
        it('stamps the original scheduled time onto invocation state on the first running row', async () => {
            const invocation = createExampleInvocation()
            invocation.queueScheduledAt = DateTime.utc(2026, 1, 1, 0, 0, 0)
            service.queueLifecycleRow(invocation, 'running')
            await service.flush()

            const rows = parseProducedRows(outputs)
            expect(rows[0].first_scheduled_at).toBe(rows[0].scheduled_at)
            expect(invocation.state.firstScheduledAt).toBe(rows[0].scheduled_at)
        })

        it('keeps the original first_scheduled_at on the terminal row after a fetch retry reschedules', async () => {
            const invocation = createExampleInvocation()
            invocation.queueScheduledAt = DateTime.utc(2026, 1, 1, 0, 0, 0)
            service.queueLifecycleRow(invocation, 'running')
            const original = invocation.state.firstScheduledAt

            // Simulate a cyclotron fetch retry: queueScheduledAt is overwritten
            // with a later backoff time before the terminal row is produced.
            invocation.queueScheduledAt = DateTime.utc(2026, 1, 1, 0, 5, 0)
            service.queueLifecycleRow(invocation, 'succeeded')
            await service.flush()

            const terminal = parseProducedRows(outputs).find((r) => r.status === 'succeeded')!
            expect(terminal.first_scheduled_at).toBe(original)
            expect(terminal.scheduled_at).not.toBe(terminal.first_scheduled_at)
        })
    })
})
