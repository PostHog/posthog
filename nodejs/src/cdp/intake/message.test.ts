import { parseJSON } from '~/common/utils/json-parse'
import { UUIDT } from '~/common/utils/utils'

import { CyclotronV2JobInit } from '../services/cyclotron-v2/types'
import { INTAKE_MESSAGE_MAX_BYTES, decodeIntakeMessage, encodeIntakeMessage, intakeJobInit } from './message'

const RUN_ID = '0193a7b2-5c1e-7d3f-9a4b-2c8d6e0f1a2b'

const jobState = {
    state: {
        event: { uuid: 'event-1', event: '$transactional_email', distinct_id: 'person-1' },
        actionStepCount: 0,
        variables: { first_name: 'Ada' },
        acceptedAt: '2026-11-11T10:00:00.000Z',
    },
    queueMetadata: { teamCapped: false },
}

const job = (overrides: Partial<CyclotronV2JobInit> = {}): CyclotronV2JobInit & { id: string } => ({
    id: RUN_ID,
    teamId: 7,
    functionId: '0193a7b2-0000-7000-8000-000000000001',
    queueName: 'email',
    priority: 1,
    scheduled: new Date('2026-11-11T10:00:00.000Z'),
    parentRunId: null,
    state: Buffer.from(JSON.stringify(jobState)),
    distinctId: 'person-1',
    personId: null,
    actionId: null,
    ...overrides,
})

const wireValue = (message: unknown): Buffer => Buffer.from(JSON.stringify(message))

const nested = (depth: number): unknown => parseJSON('{"x":'.repeat(depth) + '0' + '}'.repeat(depth))

const validWireMessage = {
    v: 1,
    kind: 'transactional-email',
    teamId: 7,
    fingerprint: 'abc123',
    job: {
        id: RUN_ID,
        functionId: '0193a7b2-0000-7000-8000-000000000001',
        queueName: 'email',
        priority: 1,
        scheduled: '2026-11-11T10:00:00.000Z',
        parentRunId: null,
        distinctId: 'person-1',
        personId: null,
        actionId: null,
        state: jobState,
    },
}

describe('intake message', () => {
    it.each([
        ['without files, with no file size field', undefined, validWireMessage],
        ['without files, with a null size, with no file size field', null, validWireMessage],
        [
            'with files, with their size',
            1000,
            { ...validWireMessage, job: { ...validWireMessage.job, fileBytes: 1000 } },
        ],
        [
            'with one empty file, with a size of zero',
            0,
            { ...validWireMessage, job: { ...validWireMessage.job, fileBytes: 0 } },
        ],
    ])(
        'carries the job state as JSON, keyed and headed by the run, and decodes to the same job, for a send %s',
        (_case, fileBytes, wire) => {
            const encoded = encodeIntakeMessage({
                kind: 'transactional-email',
                fingerprint: 'abc123',
                job: job({ fileBytes }),
            })

            expect(encoded).toEqual({
                status: 'encoded',
                message: {
                    key: RUN_ID,
                    value: expect.any(Buffer),
                    headers: {
                        intake_version: '1',
                        team_id: '7',
                        run_kind: 'transactional-email',
                        run_id: RUN_ID,
                    },
                },
            })
            if (encoded.status !== 'encoded') {
                throw new Error('expected an encoded message')
            }
            expect(parseJSON(encoded.message.value.toString())).toEqual(wire)

            const decoded = decodeIntakeMessage(encoded.message.value)
            if (decoded.status !== 'decoded') {
                throw new Error(`expected a decoded message, got ${decoded.status}`)
            }
            expect(decoded.message.fingerprint).toBe('abc123')
            expect(decoded.message.job.state?.state?.acceptedAt).toBe('2026-11-11T10:00:00.000Z')
            const { state, ...rest } = intakeJobInit(decoded.message)
            const { state: originalState, ...originalRest } = job()
            expect(rest).toEqual({ ...originalRest, fileBytes: fileBytes ?? null })
            expect(parseJSON(state!.toString())).toEqual(parseJSON(originalState!.toString()))
        }
    )

    it('decodes a keyless webhook run, whose run id is the invocation id and carries no fingerprint', () => {
        const encoded = encodeIntakeMessage({
            kind: 'workflow-webhook',
            job: job({ id: new UUIDT().toString(), queueName: 'hogflow', distinctId: null }),
        })
        if (encoded.status !== 'encoded') {
            throw new Error('expected an encoded message')
        }

        const decoded = decodeIntakeMessage(encoded.message.value)

        expect(decoded).toMatchObject({ status: 'decoded', message: { kind: 'workflow-webhook', teamId: 7 } })
        expect(decoded.status === 'decoded' && decoded.message.fingerprint).toBeUndefined()
    })

    it.each([
        ['a distinct id that fits every index it lands in', 'x'.repeat(2_000), 'encoded'],
        ['a distinct id too long for its index', 'x'.repeat(2_700), 'invalid'],
        ['a function id that is not a UUID', null, 'invalid'],
    ])('encodes only what the consumer can insert: %s', (_case, distinctId, status) => {
        const encoded = encodeIntakeMessage({
            kind: 'transactional-email',
            job: job(distinctId === null ? { functionId: 'flow-1' } : { distinctId }),
        })

        expect(encoded.status).toBe(status)
        if (encoded.status === 'encoded') {
            expect(decodeIntakeMessage(encoded.message.value).status).toBe('decoded')
        }
    })

    it('refuses a state nested past the depth limit instead of encoding it', () => {
        const deep = job({ state: Buffer.from(JSON.stringify({ ...jobState, state: { variables: nested(300) } })) })

        expect(encodeIntakeMessage({ kind: 'workflow-webhook', job: deep })).toEqual({ status: 'invalid' })
    })

    it('refuses a message over the size limit instead of encoding it', () => {
        const padding = 'x'.repeat(INTAKE_MESSAGE_MAX_BYTES)
        const large = job({ state: Buffer.from(JSON.stringify({ ...jobState, queueMetadata: { padding } })) })

        const encoded = encodeIntakeMessage({ kind: 'transactional-email', fingerprint: 'abc123', job: large })

        expect(encoded).toEqual({ status: 'too_large', bytes: expect.any(Number) })
        expect(encoded.status === 'too_large' && encoded.bytes).toBeGreaterThan(INTAKE_MESSAGE_MAX_BYTES)
    })

    it.each([
        ['an empty value', null, 'not_json'],
        ['bytes that are not JSON', Buffer.from('{"v":1,'), 'not_json'],
        ['a JSON value that is not an object', wireValue('hello'), 'schema_invalid'],
        ['a message without a version', wireValue({ ...validWireMessage, v: undefined }), 'schema_invalid'],
        ['a message from a newer version', wireValue({ ...validWireMessage, v: 2 }), 'schema_invalid'],
        ['an unknown run kind', wireValue({ ...validWireMessage, kind: 'sms' }), 'schema_invalid'],
        [
            'a run id that is not a UUID',
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, id: 'not-a-uuid' } }),
            'schema_invalid',
        ],
        [
            'an accept time that is not an ISO time',
            wireValue({
                ...validWireMessage,
                job: { ...validWireMessage.job, state: { state: { ...jobState.state, acceptedAt: 'earlier' } } },
            }),
            'schema_invalid',
        ],
        // The cyclotron row refuses these, which would fail the whole insert batch instead of this message.
        [
            'a function id that is not a UUID',
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, functionId: 'flow-1' } }),
            'schema_invalid',
        ],
        [
            'a priority past the SMALLINT column',
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, priority: 32768 } }),
            'schema_invalid',
        ],
        ['a team id past the INT column', wireValue({ ...validWireMessage, teamId: 2 ** 31 }), 'schema_invalid'],
        [
            'an indexed text column too long for its index entry',
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, distinctId: 'x'.repeat(2_700) } }),
            'schema_invalid',
        ],
        [
            'a state nested past the depth limit',
            wireValue({
                ...validWireMessage,
                job: { ...validWireMessage.job, state: { state: { ...jobState.state, variables: nested(300) } } },
            }),
            'schema_invalid',
        ],
        [
            'a file size that is not a whole number of bytes',
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, fileBytes: 10.5 } }),
            'schema_invalid',
        ],
        [
            'a text column holding a NUL character',
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, distinctId: 'person\u0000-1' } }),
            'schema_invalid',
        ],
    ])('dead-letters %s', (_case, value, reason) => {
        expect(decodeIntakeMessage(value)).toEqual({ status: 'dead_letter', reason })
    })

    it('ignores fields a newer producer of the same version adds', () => {
        const decoded = decodeIntakeMessage(wireValue({ ...validWireMessage, lane: 'bulk' }))

        expect(decoded).toMatchObject({ status: 'decoded', message: { teamId: 7 } })
    })

    it.each([
        ['a send from a producer that does not write the file size, as one without files', undefined, null],
        ['a send whose only file is empty', 0, 0],
    ])('reads the file size of %s', (_case, fileBytes, read) => {
        const decoded = decodeIntakeMessage(
            wireValue({ ...validWireMessage, job: { ...validWireMessage.job, fileBytes } })
        )
        if (decoded.status !== 'decoded') {
            throw new Error(`expected a decoded message, got ${decoded.status}`)
        }

        expect(intakeJobInit(decoded.message).fileBytes).toBe(read)
    })
})
