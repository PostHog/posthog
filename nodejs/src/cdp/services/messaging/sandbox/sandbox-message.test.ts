import { SandboxRenderedEmail, buildSandboxMessage } from './sandbox-message'

const organizationId = '00000000-0000-0000-0000-000000000001'
const footer = `This email was sent by Example organization via PostHog with the PostHog sandbox sender. Organization ID: ${organizationId}.`

const build = (email: Partial<SandboxRenderedEmail>, organizationName = 'Example organization') =>
    buildSandboxMessage({
        email: { to: { email: 'Member@example.com', name: 'Member' }, subject: 'Hello', ...email },
        organizationId,
        organizationName,
        fromAddress: 'sandbox@example.com',
        recipient: 'member@example.com',
    })

describe('buildSandboxMessage', () => {
    it('sends from the fixed address to the stored member address, with the organization header and no reply-to', () => {
        expect(build({ text: 'Hi' })).toEqual({
            from: { address: 'sandbox@example.com', name: 'Example organization via PostHog' },
            to: { address: 'member@example.com', name: 'Member' },
            subject: 'Hello',
            text: `Hi\n\n${footer}`,
            headers: [{ name: 'X-PostHog-Organization-Id', value: organizationId }],
        })
    })

    it.each([
        [
            'before the closing body tag',
            '<html><body><p>Hi</p></body></html>',
            `<html><body><p>Hi</p><div>${footer}</div></body></html>`,
        ],
        [
            'before the last closing body tag, whatever its case',
            '<body><p>a</p></body><p>b</p></BODY >',
            `<body><p>a</p></body><p>b</p><div>${footer}</div></BODY >`,
        ],
        [
            'at the end of a fragment, with no tracking pixel',
            '<p>Hi <a href="https://example.com">x</a></p>',
            `<p>Hi <a href="https://example.com">x</a></p><div>${footer}</div>`,
        ],
    ])('adds the HTML footer %s and leaves links as written', (_case, html, expected) => {
        expect(build({ html }).html).toBe(expected)
    })

    it('puts the preview text after the opening body tag', () => {
        expect(build({ html: '<body><p>Hi</p></body>', preheader: 'Preview' }).html).toMatch(
            /^<body><span style="display:none[^"]*">Preview<\/span><p>Hi<\/p><div>/
        )
    })

    it('keeps markup and header breaks in the organization name out of the From name, footer, and subject', () => {
        const message = build(
            { html: '<p>Hi</p>', text: 'Hi', subject: 'Hello\r\nBcc: someone@example.com' },
            '<b>Tom</b> & "Jerry"\r\nBcc: someone@example.com'
        )

        expect(message.from.name).toBe('<b>Tom</b> & "Jerry"Bcc: someone@example.com via PostHog')
        expect(message.subject).toBe('Hello Bcc: someone@example.com')
        expect(message.html).toContain(
            '<div>This email was sent by &lt;b&gt;Tom&lt;/b&gt; &amp; &quot;Jerry&quot;Bcc: someone@example.com via PostHog with'
        )
        expect(message.text).not.toMatch(/\r|\nBcc/)
    })
})
