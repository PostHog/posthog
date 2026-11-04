import { defaultTreeAdapter, parse } from 'parse5'

import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { TeamManager } from '~/common/utils/team-manager'

import { SandboxEmailSender } from './sandbox-email-sender'

const footer =
    'This email was sent by Example organization via PostHog with the PostHog sandbox sender. Organization ID: 00000000-0000-0000-0000-000000000001.'
const teamManager = {
    getTeam: jest.fn().mockResolvedValue({ organization_id: '00000000-0000-0000-0000-000000000001' }),
} as unknown as TeamManager
const blockedEventRedis = { useClient: jest.fn() }
const sender = new SandboxEmailSender(
    {
        enabled: true,
        tenantName: 'sandbox-tenant',
        configurationSetName: 'sandbox-email',
        fromAddress: 'fixed-sandbox@example.com',
    },
    teamManager,
    blockedEventRedis
)
const params = (html: string, text?: string, preheader?: string): CyclotronInvocationQueueParametersEmailType => ({
    type: 'email',
    from: { integrationId: 4 },
    to: { email: 'member@example.com' },
    subject: 'Hello',
    html,
    text,
    preheader,
})

describe('sandbox email content', () => {
    it.each([
        '<style>div{display:none}</style><p>Visible message</p>',
        '<style>body{background:#101010;color:white;font:24px Arial}body p{background:#101010}</style><p>Visible message</p>',
    ])('preserves template selectors and inherited presentation: %s', async (html) => {
        const result = await sender.withIdentificationFooter(params(html), 'Example organization via PostHog', 1)
        const root = parse(result.html!).childNodes.find(defaultTreeAdapter.isElementNode)!
        const body = root.childNodes.filter(defaultTreeAdapter.isElementNode).find((node) => node.tagName === 'body')!
        expect(body.childNodes.some((node) => defaultTreeAdapter.isElementNode(node) && node.tagName === 'p')).toBe(
            true
        )
        for (const ancestor of [root, body]) {
            expect(ancestor.attrs.find((attribute) => attribute.name === 'style')?.value).not.toContain('all:initial')
        }
    })
    it('keeps escaped preview values as text inside noscript', async () => {
        const result = await sender.withIdentificationFooter(
            params(
                '<table><tbody><tr><td>Hello</td></tr></tbody></table>',
                undefined,
                '<noscript>&lt;/noscript&gt;&lt;img src=x onerror=alert(1)&gt;</noscript>'
            ),
            'Example organization via PostHog',
            1
        )
        expect(result.html).toContain('&lt;img')
        expect(result.html).not.toContain('<img')
    })
    it('normalizes route settings before sending', async () => {
        const paddedSender = new SandboxEmailSender(
            {
                ...sender.config,
                tenantName: ' sandbox-tenant ',
                configurationSetName: ' sandbox-email ',
                fromAddress: ' fixed-sandbox@example.com ',
            },
            teamManager,
            blockedEventRedis
        )
        const result = await paddedSender.withIdentificationFooter(
            params('<p>Hello</p>'),
            'Example organization via PostHog',
            1
        )
        expect(result.from.email).toBe('fixed-sandbox@example.com')
        expect(paddedSender.config).toMatchObject({
            tenantName: 'sandbox-tenant',
            configurationSetName: 'sandbox-email',
        })
    })
    it('preserves already escaped preview text', async () => {
        const result = await sender.withIdentificationFooter(
            params(
                '<body><table><tbody><tr><td>Hello</td></tr></tbody></table></body>',
                undefined,
                'Tom &amp; Jerry&nbsp;'
            ),
            'Example organization via PostHog',
            1
        )
        expect(result.html).toContain('Tom &amp; Jerry&nbsp;')
        expect(result.html).not.toContain('&amp;amp;')
    })
    it.each([
        [
            'an unclosed comment',
            'height:30px!important;overflow:hidden!important;/*',
            'height:30px!important;overflow:hidden!important',
        ],
        ['an unclosed string', 'height:30px!important;font-family:"Arial', 'height:30px!important'],
        ['an unclosed bracket', 'overflow:hidden!important;background:url(x.png', 'overflow:hidden!important'],
        [
            'a quote inside an unquoted url',
            'height:400px!important;overflow:hidden!important;background:url(a"b);c:d")',
            'height:400px!important;overflow:hidden!important',
        ],
        [
            'an unquoted url',
            'background:url( x.png );height:30px!important',
            'background:url( x.png );height:30px!important',
        ],
        [
            'an escaped quote',
            'height:30px!important;content:"a\\";overflow:hidden!important;"',
            'height:30px!important',
        ],
        [
            'a line break in a string',
            'height:30px!important;content:"a\nb";overflow:hidden!important',
            'height:30px!important',
        ],
        ['a closed comment', 'margin:0/* note */;height:30px!important', 'margin:0 ;height:30px!important'],
        [
            'a comment between a slash and a star',
            'height:30px!important;overflow:hidden!important;--x: //**/*',
            'height:30px!important;overflow:hidden!important;--x: / *',
        ],
    ])('keeps the visibility overrides in effect after %s in the template style', async (_case, style, kept) => {
        const html = `<html style='${style}'><body style='${style}'><p>Visible message</p></body></html>`
        const result = await sender.withIdentificationFooter(params(html), 'Example organization via PostHog', 1)
        const root = parse(result.html!).childNodes.find(defaultTreeAdapter.isElementNode)!
        const body = root.childNodes.filter(defaultTreeAdapter.isElementNode).find((node) => node.tagName === 'body')!
        for (const ancestor of [root, body]) {
            const value = ancestor.attrs.find((attribute) => attribute.name === 'style')!.value
            expect(value.startsWith(`${kept};display:block!important;`)).toBe(true)
            expect(value.endsWith(';zoom:1!important')).toBe(true)
            expect(value).not.toContain('/*')
        }
    })
    it.each([
        '<html style="overflow:hidden"><body style="margin:0;height:20px;overflow:hidden"><p>Visible message</p></body></html>',
        '<html style="height:20px;clip-path:inset(0)"><body style="height:20px;clip-path:inset(0)"><p>Visible message</p></body></html>',
        '<html style="margin-top:-100000px"><body style="margin-left:-100000px"><p style="margin-left:100000px">Visible message</p></body></html>',
    ])('keeps document ancestors outside the template layout: %s', async (html) => {
        const result = await sender.withIdentificationFooter(params(html), 'Example organization via PostHog', 1)
        const root = parse(result.html!).childNodes.find(defaultTreeAdapter.isElementNode)!
        const body = root.childNodes.filter(defaultTreeAdapter.isElementNode).find((node) => node.tagName === 'body')!
        for (const ancestor of [root, body]) {
            const value = ancestor.attrs.find((attribute) => attribute.name === 'style')?.value
            expect(value).toContain('height:auto!important')
            expect(value).toContain('margin:0!important')
        }
        expect(result.html).toContain('Visible message')
        expect(body.childNodes.at(-1)).toMatchObject({ childNodes: [{ nodeName: '#text', value: footer }] })
    })
    it.each([
        [
            '<body>Hello <a href="https://example.com">there</a>.</body>',
            'Hello <a href="https://example.com">there</a>.',
            null,
        ],
        ['<body><!-- </body> --><p>Hello</p></body>', '<!-- </body> --><p>Hello</p>', null],
        [
            '<body><p>Hello</p><template><p>Example</p></template></body>',
            '<p>Hello</p><template><p>Example</p></template>',
            null,
        ],
        [
            '<body><p>Hello</p><script>const greeting = "Hello"</script></body>',
            '<p>Hello</p><script>const greeting = "Hello"</script>',
            null,
        ],
        [
            '<body><style>div { display: none } /* </body> */</style><p>Hello</p></body>',
            '<style>div { display: none } /* </body> */</style><p>Hello</p>',
            null,
        ],
        ['<body><textarea>Hello </body>', '<textarea>Hello &lt;/body&gt;</textarea>', null],
        ['<body><plaintext>Hello </body>', '<pre>Hello &lt;/body&gt;</pre>', null],
        ['<body><p>Hello</p><template><plaintext>Example', '<p>Hello</p><template><pre>Example</pre></template>', null],
        ['<head><template><plaintext>Example', '<head><template><pre>Example</pre></template></head>', null],
        [
            '<body><p>Hello</p><noscript><style>p {color:blue}',
            '<p>Hello</p><div><style>p {color:blue}</style></div>',
            null,
        ],
        [
            '<body><p>Hello</p><noscript>&lt;plaintext&gt;Example</noscript></body>',
            '<p>Hello</p><div>&lt;plaintext&gt;Example</div>',
            null,
        ],
        [
            '<body><table><tbody><tr><td>Hello</td></tr></tbody></table></body>',
            '<td>Hello</td>',
            '<textarea>Preview text',
        ],
        ['<body><p>Hello</p></body>', '<p>Hello</p>', '<plaintext>Preview text'],
        ['<body><p>Hello</p><noscript><style></noscript><!--', '<p>Hello</p>', null],
        [
            '<body><p>Hello</p><noscript><style>/* </noscript><plaintext> */ p {color:blue}</style></noscript>',
            '<style>/* </noscript><plaintext> */ p {color:blue}</style>',
            null,
        ],
        [
            '<body><p>Hello</p><noscript><p title="</noscript><style>">Fallback</p></noscript></body>',
            '<p title="</noscript><style>">Fallback</p>',
            null,
        ],
        [
            '<body><noscript><style></noscript><script></style></noscript>Hello',
            '<style></noscript><script></style>',
            null,
        ],
        ['<body style="background:#525252;color:white"><p>Hello</p></body>', '<p>Hello</p>', null],
    ])('retains the footer outside template content: %s', async (html, expectedContent, preheader) => {
        const result = await sender.withIdentificationFooter(
            params(html, undefined, preheader ?? undefined),
            'Example organization via PostHog',
            1
        )
        expect(result.html).toContain(expectedContent)
        for (const scriptingEnabled of [false, true]) {
            const root = parse(result.html!, { scriptingEnabled }).childNodes.find(defaultTreeAdapter.isElementNode)
            const body = root?.childNodes
                .filter(defaultTreeAdapter.isElementNode)
                .find((node) => node.tagName === 'body')
            expect(body?.childNodes.at(-1)).toMatchObject({
                tagName: 'div',
                childNodes: [{ nodeName: '#text', value: footer }],
            })
        }
        expect(result.preheader).toBeUndefined()
    })
    it.each([
        ['<body><p>Hello</p><script><!--<script>', null, null],
        ['<body><p>Hello</p><template><script><!--<script>', null, null],
        ['', '', 'The sandbox email template must include HTML or text content. Update the template and try again.'],
    ])('rejects content that cannot retain the footer: %s', async (html, text, error) => {
        await expect(
            sender.withIdentificationFooter(params(html, text ?? undefined), 'Example organization via PostHog', 1)
        ).rejects.toThrow(
            error ??
                'The sandbox email template could not retain its identification footer. Update the template and try again.'
        )
    })
})
