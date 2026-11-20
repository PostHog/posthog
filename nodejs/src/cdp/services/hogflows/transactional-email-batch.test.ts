import {
    BatchCapacity,
    CodeSendBatchRequestSchema,
    TemplateBatchRequestSchema,
    slotRequestOf,
} from './transactional-email-batch'

describe('transactional email batch', () => {
    describe('BatchCapacity', () => {
        it('refuses a request over the cap until an admitted one releases', () => {
            const capacity = new BatchCapacity(1)
            const release = capacity.admit()

            expect(release).not.toBeNull()
            expect(capacity.admit()).toBeNull()

            release!()

            expect(capacity.admit()).not.toBeNull()
            expect(capacity.admit()).toBeNull()
        })
    })

    describe('slotRequestOf', () => {
        it("keeps the batch's variables and lets a recipient's own value win", () => {
            const recipient = {
                to: 'ada@example.com',
                distinct_id: 'ada',
                idempotency_key: 'key-ada',
                variables: { link: 'https://example.com/ada' },
            }
            const batch = { variables: { link: 'https://example.com/shared', name: 'Shared' }, recipients: [recipient] }

            expect(slotRequestOf(batch, recipient)).toEqual(
                expect.objectContaining({ variables: { link: 'https://example.com/ada', name: 'Shared' } })
            )
        })
    })

    describe('TemplateBatchRequestSchema', () => {
        it.each([
            [100, true],
            [101, false],
        ])('takes a list of %i recipients: %s', (count, accepted) => {
            const recipients = Array.from({ length: count }, (_, i) => ({
                to: `person-${i}@example.com`,
                distinct_id: `person-${i}`,
                idempotency_key: `key-${i}`,
            }))

            expect(TemplateBatchRequestSchema.safeParse({ recipients }).success).toBe(accepted)
        })
    })

    describe('whole-batch refusals', () => {
        const ada = { to: 'ada@example.com', distinct_id: 'person-ada', idempotency_key: 'key-ada' }
        const bo = { to: 'bo@example.com', distinct_id: 'person-bo', idempotency_key: 'key-bo' }
        const send = { content: { subject: 'Hello', text: 'Hi' }, tracking: { captureEngagement: false } }

        it.each([
            {
                batch: 'a code send batch',
                schema: CodeSendBatchRequestSchema,
                body: { send, recipients: [ada, bo] },
                accepted: true,
            },
            {
                batch: 'a repeated idempotency key',
                schema: TemplateBatchRequestSchema,
                body: { recipients: [ada, { ...bo, idempotency_key: ada.idempotency_key }] },
                accepted: false,
            },
            {
                batch: 'a send time for the batch',
                schema: TemplateBatchRequestSchema,
                body: { scheduled_at: '2030-01-01T00:00:00Z', recipients: [ada] },
                accepted: false,
            },
            {
                batch: 'a send time for one recipient',
                schema: TemplateBatchRequestSchema,
                body: { recipients: [ada, { ...bo, scheduled_at: '2030-01-01T00:00:00Z' }] },
                accepted: false,
            },
            {
                batch: 'cc on a code send',
                schema: CodeSendBatchRequestSchema,
                body: { send: { ...send, cc: ['cy@example.com'] }, recipients: [ada] },
                accepted: false,
            },
            {
                batch: 'bcc on a code send',
                schema: CodeSendBatchRequestSchema,
                body: { send: { ...send, bcc: ['cy@example.com'] }, recipients: [ada] },
                accepted: false,
            },
            {
                batch: 'attachments on a code send',
                schema: CodeSendBatchRequestSchema,
                body: { send: { ...send, attachments: [] }, recipients: [ada] },
                accepted: false,
            },
        ])('$batch is accepted: $accepted', ({ schema, body, accepted }) => {
            expect(schema.safeParse(body).success).toBe(accepted)
        })
    })
})
