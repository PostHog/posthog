import { DateTime } from 'luxon'

import { CyclotronJobInvocation } from '../../types'
import { JobRow, encodeJob, v2JobToInvocation } from './job-codec'

// The golden `state` strings are what the Postgres-v2 adapter wrote before the codec existed. Workers of both
// versions read the same rows during a deploy, so the bytes must not change.
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
    it.each(cases)('encodes $name byte-identically and decodes it back', ({ invocation, golden, columns }) => {
        const init = encodeJob(invocation)
        expect(init.state?.toString('utf-8')).toBe(golden)
        expect({ ...init, state: undefined }).toEqual({ ...columns, state: undefined })

        const dequeuedAt = DateTime.fromISO('2026-11-04T08:00:00.000Z', { zone: 'utc' })
        const row: JobRow = {
            id: invocation.id,
            teamId: invocation.teamId,
            functionId: invocation.functionId,
            queueName: invocation.queue,
            priority: invocation.queuePriority,
            scheduled: dequeuedAt,
            created: dequeuedAt,
            parentRunId: invocation.parentRunId ?? null,
            state: Buffer.from(golden, 'utf-8'),
            cancelRequestedAt: null,
        }

        expect(v2JobToInvocation(row)).toEqual({
            ...invocation,
            queueParameters: invocation.queueParameters ?? undefined,
            queueMetadata: invocation.queueMetadata ?? undefined,
            queueScheduledAt: dequeuedAt,
            queueCreatedAt: dequeuedAt,
            queueDueAt: dequeuedAt,
            queueSource: 'postgres-v2',
        })
    })
})
