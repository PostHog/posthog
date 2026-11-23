import {
    BATCH_COPIED_BYTES_MAX,
    BATCH_COPIED_NODES_MAX,
    BATCH_VARIABLE_DEPTH_MAX,
    BatchCapacity,
    CodeSendBatchRequestSchema,
    TemplateBatchRequestSchema,
    exceedsCopyLimits,
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

    describe('exceedsCopyLimits', () => {
        const nestedOf = (levels: number): Record<string, unknown> => {
            let value: Record<string, unknown> = {}
            for (let level = 1; level < levels; level++) {
                value = { a: value }
            }
            return value
        }
        const recipient = (name: string, variables?: Record<string, unknown>) => ({
            to: `${name}@example.com`,
            distinct_id: name,
            idempotency_key: `key-${name}`,
            ...(variables && { variables }),
        })
        // Each of the two recipients copies {"p":"<padding>"}, 8 bytes around the padding, and its own {}, 2 bytes.
        const paddingAtLimit = BATCH_COPIED_BYTES_MAX / 2 - 10
        // Each of the two recipients copies the keys a and b and the list's elements.
        const nodesTo = (elements: number) => ({
            variables: { a: { b: Array.from({ length: elements }, (_, i) => i) } },
            recipients: [recipient('ada'), recipient('bo')],
        })
        const paddedTo = (padding: number) => ({
            variables: { p: 'x'.repeat(padding) },
            recipients: [recipient('ada'), recipient('bo')],
        })

        it.each([
            {
                batch: 'shared variables nested to the depth limit',
                body: { variables: nestedOf(BATCH_VARIABLE_DEPTH_MAX), recipients: [recipient('ada')] },
                exceeds: false,
            },
            {
                batch: 'shared variables nested one level deeper',
                body: { variables: nestedOf(BATCH_VARIABLE_DEPTH_MAX + 1), recipients: [recipient('ada')] },
                exceeds: true,
            },
            {
                batch: "a recipient's own variables nested one level deeper",
                body: { variables: {}, recipients: [recipient('ada', nestedOf(BATCH_VARIABLE_DEPTH_MAX + 1))] },
                exceeds: true,
            },
            { batch: 'copies at the byte limit', body: paddedTo(paddingAtLimit), exceeds: false },
            { batch: 'copies one byte over the limit', body: paddedTo(paddingAtLimit + 1), exceeds: true },
            {
                batch: 'nested keys and elements at the node limit',
                body: nodesTo(BATCH_COPIED_NODES_MAX / 2 - 2),
                exceeds: false,
            },
            {
                batch: 'nested keys and elements one node over the limit',
                body: nodesTo(BATCH_COPIED_NODES_MAX / 2 - 1),
                exceeds: true,
            },
            {
                batch: 'a full code send of a large html email',
                body: {
                    variables: { company: 'Example' },
                    send: {
                        content: { subject: 'Hello', html: 'x'.repeat(100 * 1024) },
                        tracking: { captureEngagement: false },
                    },
                    recipients: Array.from({ length: 100 }, (_, i) =>
                        recipient(`person-${i}`, { first_name: `Person ${i}`, link: `https://example.com/${i}` })
                    ),
                },
                exceeds: false,
            },
            {
                batch: 'a code send whose content each recipient copies over the limit',
                body: {
                    variables: {},
                    send: {
                        content: { subject: 'Hello', html: 'x'.repeat(BATCH_COPIED_BYTES_MAX / 2) },
                        tracking: { captureEngagement: false },
                    },
                    recipients: [recipient('ada'), recipient('bo')],
                },
                exceeds: true,
            },
        ])('$batch exceeds the copy limits: $exceeds', ({ body, exceeds }) => {
            expect(exceedsCopyLimits(body)).toBe(exceeds)
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
