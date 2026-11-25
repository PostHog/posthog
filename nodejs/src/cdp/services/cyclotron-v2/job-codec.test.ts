import { DateTime } from 'luxon'

import { parseJSON } from '~/common/utils/json-parse'

import { CyclotronJobInvocation } from '../../types'
import { EncryptedFields } from '../../utils/encryption-utils'
import { JobRow, encodeJob, v2JobToInvocation, withReschedule } from './job-codec'

const codeSend: CyclotronJobInvocation = {
    id: '019a4f3e-7c1d-7000-8000-00000000c0de',
    teamId: 2,
    functionId: '019a4f3e-7c1d-7000-8000-00000000f10e',
    parentRunId: '019a4f3e-7c1d-7000-8000-0000000000aa',
    queue: 'email',
    queuePriority: 1,
    queueScheduledAt: DateTime.fromISO('2026-11-05T09:30:00.000Z', { zone: 'utc' }),
    queueParameters: {
        type: 'email',
        to: { email: 'ada@example.com', name: 'Ada' },
        from: { integrationId: 7, email: 'no-reply@example.com' },
        subject: 'Hi <b>there</b>',
        html: '<p>Hello "Ada"</p>\n',
    },
    queueMetadata: { attempt: 2, note: 'ünïcødé ✉' },
    state: {
        event: {
            uuid: 'e-1',
            event: '$transactional_email',
            distinct_id: 'user-42',
            properties: { to: 'ada@example.com' },
        },
        personId: 'p-7',
        currentAction: { id: 'action_email', startedAtTimestamp: 1762335000000 },
        send: { subject: 'Hi <b>there</b>', html: '<p>Hello "Ada"</p>\n', from: { email: 'no-reply@example.com' } },
        triggerMetricPending: true,
    },
}

const bare: CyclotronJobInvocation = {
    id: '019a4f3e-7c1d-7000-8000-00000000b4e0',
    teamId: 3,
    functionId: '019a4f3e-7c1d-7000-8000-00000000f10f',
    queue: 'hog',
    queuePriority: 0,
    queueParameters: null,
    queueMetadata: null,
    state: null,
}

const cases = [
    {
        name: 'a code send with lookup columns, parameters and metadata',
        invocation: codeSend,
        golden: String.raw`{"state":{"event":{"uuid":"e-1","event":"$transactional_email","distinct_id":"user-42","properties":{"to":"ada@example.com"}},"personId":"p-7","currentAction":{"id":"action_email","startedAtTimestamp":1762335000000},"send":{"subject":"Hi <b>there</b>","html":"<p>Hello \"Ada\"</p>\n","from":{"email":"no-reply@example.com"}},"triggerMetricPending":true},"queueParameters":{"type":"email","to":{"email":"ada@example.com","name":"Ada"},"from":{"integrationId":7,"email":"no-reply@example.com"},"subject":"Hi <b>there</b>","html":"<p>Hello \"Ada\"</p>\n"},"queueMetadata":{"attempt":2,"note":"ünïcødé ✉"}}`,
        columns: {
            id: codeSend.id,
            teamId: 2,
            functionId: codeSend.functionId,
            queueName: 'email',
            priority: 1,
            scheduled: new Date('2026-11-05T09:30:00.000Z'),
            parentRunId: codeSend.parentRunId,
            distinctId: 'user-42',
            personId: 'p-7',
            actionId: 'action_email',
        },
    },
    {
        name: 'a bare invocation with null state',
        invocation: bare,
        golden: '{"state":null}',
        columns: {
            id: bare.id,
            teamId: 3,
            functionId: bare.functionId,
            queueName: 'hog',
            priority: 0,
            scheduled: expect.any(Date),
            parentRunId: null,
            distinctId: null,
            personId: null,
            actionId: null,
        },
    },
]

describe('job codec', () => {
    const dequeuedAt = DateTime.fromISO('2026-11-04T08:00:00.000Z', { zone: 'utc' })
    const rowWith = (invocation: CyclotronJobInvocation, state: Buffer): JobRow => ({
        id: invocation.id,
        teamId: invocation.teamId,
        functionId: invocation.functionId,
        queueName: invocation.queue,
        priority: invocation.queuePriority,
        scheduled: dequeuedAt,
        created: dequeuedAt,
        parentRunId: invocation.parentRunId ?? null,
        state,
        cancelRequestedAt: null,
    })
    const dequeued = (invocation: CyclotronJobInvocation): CyclotronJobInvocation => ({
        ...invocation,
        queueParameters: invocation.queueParameters ?? undefined,
        queueMetadata: invocation.queueMetadata ?? undefined,
        queueScheduledAt: dequeuedAt,
        queueCreatedAt: dequeuedAt,
        queueDueAt: dequeuedAt,
        queueSource: 'postgres-v2',
    })

    it.each(cases)('writes $name as the earlier adapter did', ({ invocation, golden, columns }) => {
        const init = encodeJob(invocation)

        expect(parseJSON(init.state!.toString('utf-8'))).toEqual(parseJSON(golden))
        expect({ ...init, state: undefined }).toEqual({ ...columns, state: undefined })
        expect(v2JobToInvocation(rowWith(invocation, init.state!))).toEqual(dequeued(invocation))
    })

    it.each(cases)('reads $name as the earlier adapter wrote it', ({ invocation, golden }) => {
        expect(v2JobToInvocation(rowWith(invocation, Buffer.from(golden, 'utf-8')))).toEqual(dequeued(invocation))
    })

    const keys = new EncryptedFields('00beef0000beef0000beef0000beef00')
    const sealedCodeSend = (sealed: string): Buffer => {
        const { state, queueMetadata } = parseJSON(cases[0].golden)
        const { send: _send, event, ...publicState } = state
        const { properties: _properties, ...publicEvent } = event
        return Buffer.from(
            JSON.stringify({ state: { ...publicState, event: publicEvent }, queueMetadata, sealed }),
            'utf-8'
        )
    }
    const sealFor = ({ id, teamId }: { id: string; teamId: number }, encrypter = keys): string =>
        encrypter.encrypt(
            JSON.stringify({
                teamId,
                id,
                fields: [
                    [['state', 'send'], codeSend.state!.send],
                    [['state', 'event', 'properties'], codeSend.state!.event.properties],
                    [['queueParameters'], codeSend.queueParameters],
                ],
            })
        )

    it('reads a sealed code send as the plaintext one', () => {
        const stored = sealedCodeSend(sealFor(codeSend))

        expect(stored.toString('utf-8')).not.toContain('Hello')
        expect(v2JobToInvocation(rowWith(codeSend, stored), keys)).toEqual(dequeued(codeSend))
    })

    it.each([
        ['another job', sealFor({ ...codeSend, id: bare.id })],
        ['another team', sealFor({ ...codeSend, teamId: 3 })],
        ['a key the reader does not hold', sealFor(codeSend, new EncryptedFields('11beef0000beef0000beef0000beef11'))],
        ['no key at all', 'not-a-token'],
        ['a reader with no keys', sealFor(codeSend), new EncryptedFields('')],
        [
            'a field outside state and queueParameters',
            keys.encrypt(
                JSON.stringify({ teamId: 2, id: codeSend.id, fields: [[['queueMetadata'], { attempt: 99 }]] })
            ),
        ],
    ])('runs nothing from a code send sealed for %s', (_desc, sealed, opener = keys) => {
        const invocation = v2JobToInvocation(rowWith(codeSend, sealedCodeSend(sealed)), opener)

        expect(invocation.stateUnreadable).toBe(true)
        expect(invocation.state?.send).toBeUndefined()
        expect(invocation.queueParameters).toBeUndefined()
        expect(invocation.queueMetadata).toEqual(codeSend.queueMetadata)
    })

    it.each([
        ['no earlier status row', undefined, '2026-11-09T10:00:00.000Z'],
        ['an earlier one in the past', '2026-11-09T09:59:59.000Z', '2026-11-09T10:00:00.000Z'],
        ['an earlier one in the same millisecond', '2026-11-09T10:00:00.000Z', '2026-11-09T10:00:00.001Z'],
        ['an earlier one ahead of this clock', '2026-11-09T10:00:05.000Z', '2026-11-09T10:00:05.001Z'],
    ])('times a reschedule after %s', (_desc, previous, expected) => {
        const stored = Buffer.from(
            JSON.stringify({ state: { scheduledAt: 'old', statusAt: previous, x: 1 }, sealed: 'token' })
        )

        const { state, rescheduledAt } = withReschedule(stored, 'new', new Date('2026-11-09T10:00:00.000Z'))

        expect(rescheduledAt.toISOString()).toEqual(expected)
        expect(parseJSON(state.toString())).toEqual({
            state: { scheduledAt: 'new', statusAt: expected, x: 1 },
            sealed: 'token',
        })
    })
})
