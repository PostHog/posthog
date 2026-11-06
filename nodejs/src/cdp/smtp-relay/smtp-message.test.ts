import { parseSmtpMessage, planSends } from './smtp-message'
import { SmtpReply } from './smtp-replies'

const raw = (headers: string[], body = 'Hello'): Buffer =>
    Buffer.from([...headers, 'Content-Type: text/plain; charset=utf-8', '', body, ''].join('\r\n'))

const plan = async (headers: string[], envelopeTo: string[], from = 'envelope@example.com', body?: string) =>
    planSends(await parseSmtpMessage(raw(headers, body)), { from, to: envelopeTo })

describe('planSends', () => {
    it('sends one email per To, with copies on the first only, and takes who gets it from the envelope', async () => {
        const { sends } = await plan(
            [
                'From: Jane <jane@example.com>',
                'To: a@example.com, B Person <b@example.com>, not-in-envelope@example.com',
                'Cc: c@example.com',
                'Subject: Hi',
            ],
            ['a@example.com', 'B@EXAMPLE.COM', 'c@example.com', 'hidden@example.com']
        )

        expect(sends.map(({ body }) => [body.to, body.cc, body.bcc])).toEqual([
            ['a@example.com', ['c@example.com'], ['hidden@example.com']],
            ['B@EXAMPLE.COM', undefined, undefined],
        ])
    })

    it('still sends when every recipient is hidden', async () => {
        const { sends } = await plan(
            ['From: jane@example.com', 'To: undisclosed-recipients:;', 'Subject: Hi'],
            ['a@example.com', 'b@example.com']
        )

        expect(sends.map(({ body }) => [body.to, body.bcc])).toEqual([['a@example.com', ['b@example.com']]])
    })

    it.each([
        ['a name with a comma', 'From: "Smith, Jane" <jane@example.com>', '"Smith, Jane" <jane@example.com>'],
        ['an encoded name', 'From: =?UTF-8?Q?Zo=C3=AB?= <jane@example.com>', '"Zoë" <jane@example.com>'],
        ['no name', 'From: jane@example.com', 'jane@example.com'],
    ])('keeps the sender with %s', async (_name, header, from) => {
        const { sends } = await plan([header, 'To: a@example.com', 'Subject: Hi'], ['a@example.com'])

        expect(sends[0].body.from).toEqual(from)
    })

    it('falls back to the envelope sender and refuses two senders', async () => {
        const { sends } = await plan(['To: a@example.com', 'Subject: Hi'], ['a@example.com'], 'envelope@example.com')
        expect(sends[0].body.from).toEqual('envelope@example.com')

        await expect(
            plan(['From: a@example.com, b@example.com', 'To: a@example.com'], ['a@example.com'])
        ).rejects.toBeInstanceOf(SmtpReply)
    })

    it('fills what the send API requires but mail tools may leave out', async () => {
        const { sends } = await plan(['From: jane@example.com', 'To: a@example.com'], ['a@example.com'], undefined, '')

        expect(sends[0].body).toMatchObject({ subject: '(no subject)', template_key: 'smtp' })
        expect(sends[0].body.text).toBeTruthy()
    })

    it('forwards the headers the send API takes and reports the others', async () => {
        const { sends, droppedHeaders } = await plan(
            [
                'From: jane@example.com',
                'To: a@example.com',
                'Subject: Hi',
                'X-Entity-Ref-ID: order-1',
                'In-Reply-To: <a@example.com>',
                'References: <a@example.com>',
                '  <b@example.com>',
                'X-PostHog-Tracking-Code: forged',
                'X-SES-TENANT: team-2',
                'Sender: other@example.com',
                'X-Mailer: PHPMailer',
            ],
            ['a@example.com']
        )

        expect(sends[0].body.headers).toEqual({
            'X-Entity-Ref-ID': 'order-1',
            'In-Reply-To': '<a@example.com>',
            References: '<a@example.com> <b@example.com>',
        })
        expect(droppedHeaders).toEqual(['X-PostHog-Tracking-Code', 'X-SES-TENANT', 'Sender'])
    })

    it.each([
        ['nothing', [], false],
        ['the header', ['X-PostHog-Capture-Engagement: true'], true],
        ['a header set to something else', ['X-PostHog-Capture-Engagement: yes'], false],
    ])('tracks opens and clicks with %s', async (_name, extra, tracked) => {
        const { sends } = await plan(
            ['From: jane@example.com', 'To: a@example.com', 'Subject: Hi', ...extra],
            ['a@example.com']
        )

        expect(sends[0].body).toMatchObject({ capture_engagement: tracked, track_opens_and_clicks: tracked })
    })

    it('gives each recipient its own stable idempotency key', async () => {
        const headers = ['From: j@example.com', 'To: a@example.com, b@example.com', 'Subject: Hi', 'Message-ID: <1@x>']
        const [first, retry] = [
            await plan(headers, ['a@example.com', 'b@example.com']),
            await plan(headers, ['a@example.com', 'b@example.com']),
        ]

        expect(first.sends[0].idempotencyKey).toEqual(retry.sends[0].idempotencyKey)
        expect(first.sends[0].idempotencyKey).not.toEqual(first.sends[1].idempotencyKey)
        expect(first.sends[0].idempotencyKey).toMatch(/^[!-~]{1,255}$/)
    })

    it.each([['PostHog-Idempotency-Key: 1'], ['Resend-Idempotency-Key: 1']])(
        'prefers the explicit %s over the Message-ID',
        async (header) => {
            const headers = (messageId: string) => [
                'From: j@example.com',
                'To: a@example.com',
                'Subject: Hi',
                `Message-ID: ${messageId}`,
                header,
            ]
            const [first, second] = [
                await plan(headers('<1@x>'), ['a@example.com']),
                await plan(headers('<2@x>'), ['a@example.com']),
            ]

            expect(first.sends[0].idempotencyKey).toEqual(second.sends[0].idempotencyKey)
        }
    )

    it('leaves a message with no key or Message-ID without an idempotency key', async () => {
        const { sends } = await plan(['From: j@example.com', 'To: a@example.com', 'Subject: Hi'], ['a@example.com'])

        expect(sends[0].idempotencyKey).toBeUndefined()
    })

    it('keeps cid links, marks inline files and cleans file names', async () => {
        const boundary = 'b1'
        const message = Buffer.from(
            [
                'From: j@example.com',
                'To: a@example.com',
                'Subject: Hi',
                `Content-Type: multipart/related; boundary=${boundary}`,
                '',
                `--${boundary}`,
                'Content-Type: text/html',
                '',
                '<img src="cid:logo">',
                `--${boundary}`,
                'Content-Type: image/png; name="logo.png"',
                'Content-ID: <logo>',
                'Content-Disposition: inline; filename="logo.png"',
                'Content-Transfer-Encoding: base64',
                '',
                'aGk=',
                `--${boundary}`,
                'Content-Type: application/pdf; name="../../a.pdf"',
                'Content-Disposition: attachment; filename="../../a.pdf"',
                'Content-Transfer-Encoding: base64',
                '',
                'aGk=',
                `--${boundary}--`,
                '',
            ].join('\r\n')
        )

        const { sends } = planSends(await parseSmtpMessage(message), { to: ['a@example.com'] })

        expect(sends[0].body.html).toContain('cid:logo')
        expect(sends[0].body.attachments?.map(({ filename, content_id }) => [filename, content_id])).toEqual([
            ['logo.png', 'logo'],
            ['a.pdf', undefined],
        ])
    })

    it.each([
        ['more To addresses than a message can take', 51, 0],
        ['more Bcc addresses than a message can take', 1, 11],
    ])('refuses the whole message with %s', async (_name, toCount, bccCount) => {
        const to = Array.from({ length: toCount }, (_, i) => `t${i}@example.com`)
        const bcc = Array.from({ length: bccCount }, (_, i) => `h${i}@example.com`)

        await expect(
            plan(['From: j@example.com', `To: ${to.join(', ')}`, 'Subject: Hi'], [...to, ...bcc])
        ).rejects.toMatchObject({ responseCode: 554 })
    })

    it('refuses signed mail, which rebuilding would break', async () => {
        const message = Buffer.from(
            'From: j@example.com\r\nTo: a@example.com\r\nContent-Type: multipart/signed; boundary=b\r\n\r\n--b\r\n\r\nhi\r\n--b--\r\n'
        )

        await expect(
            parseSmtpMessage(message).then((parsed) => planSends(parsed, { to: ['a@example.com'] }))
        ).rejects.toMatchObject({ responseCode: 554 })
    })
})
