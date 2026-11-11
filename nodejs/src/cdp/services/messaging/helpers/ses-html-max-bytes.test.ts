import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { defaultConfig } from '~/common/config/config'

import { htmlForSes, tagEmailLinks } from './email-html'
import { escapeHtml, escapedHtmlByteLength } from './escape-html'
import { sesHtmlMaxBytes } from './ses-html-max-bytes'
import { EmailTrackingCodeSigner } from './tracking-code'

const SITE_URL = 'https://us.posthog.com'
const PREHEADER = 'Your files are attached'
const UTM = {
    tags: { utm_source: 'posthog', utm_medium: 'email', utm_campaign: 'Spring sale', utm_content: 'cta' },
    siteUrl: SITE_URL,
    fixedScanner: true,
}
const unclosedAnchors = (count: number): string =>
    `<body>${`<a href="https://example.com/?a='1'&b=2">x`.repeat(count)}</body>`

describe('sesHtmlMaxBytes', () => {
    const invocation = createExampleInvocation()
    const signer = new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, 'https://track.example.com')
    const maxBytes = (html: string, utm: typeof UTM | null): number =>
        sesHtmlMaxBytes(html, { utmTags: utm?.tags ?? null, invocation, signer, preheader: PREHEADER })

    it.each<{ case: string; html: string; utm?: typeof UTM | null }>([
        { case: 'a plain link', html: '<body><a href="https://example.com/p">x</a></body>' },
        { case: 'an unquoted href', html: '<body><a href=https://example.com/p>x</a></body>' },
        { case: 'raw ampersands', html: "<a href='https://example.com/?a=1&b=2&c=3&d=4'>x</a>" },
        { case: 'quotes and brackets', html: `<a href='https://example.com/?q="<>"'>x</a>` },
        {
            case: 'raw ampersands without UTM tags',
            html: `<a href="https://example.com/?${'a&'.repeat(40)}">x</a>`,
            utm: null,
        },
        {
            case: 'raw quotes without UTM tags',
            html: `<a href='https://example.com/?${'"'.repeat(40)}'>x</a>`,
            utm: null,
        },
        {
            case: 'raw quotes in a closed body without UTM tags',
            html: `<body><a href='https://example.com/?${'"'.repeat(100)}'>x</a></body>`,
            utm: null,
        },
        { case: 'entity-encoded characters', html: '<a href="https://example.com/?a=&#x22;&#39;&lt;">x</a>' },
        { case: 'padding whitespace', html: '<a href="  https://example.com/p  ">x</a>' },
        { case: 'an earlier run id', html: '<a href="https://example.com/?ph_workflow_run=old&amp;a=1">x</a>' },
        { case: 'a body tag inside the href', html: '<a href="https://example.com/?q=</body>">x</a></body>' },
        {
            case: 'many links with an existing SES tag',
            html: `<body>${'<a ses:tags="k:v" href="https://example.com/?x=\'">y</a>'.repeat(12)}</body>`,
        },
        { case: 'many anchors that never close', html: unclosedAnchors(1_000) },
        {
            case: 'UTM values with apostrophes, reserved and multi-byte characters',
            html: '<body><a href="https://example.com/p">x</a><a href="https://example.com/q">y</a></body>',
            utm: {
                ...UTM,
                tags: {
                    utm_source: "it's & <ok>",
                    utm_medium: 'é😀中',
                    utm_campaign: 'a b/c?d=e#f',
                    utm_content: "'()*!~-_.",
                },
            },
        },
    ])('bounds the bytes SES gets for $case', ({ html, utm = UTM }) => {
        const sent = htmlForSes(
            tagEmailLinks(html, utm, { runId: invocation.id, senderEmail: 'hi@example.com', siteUrl: SITE_URL }),
            { invocation, signer, isTest: false },
            PREHEADER
        )

        expect(Buffer.byteLength(sent, 'utf8')).toBeLessThanOrEqual(maxBytes(html, utm))
    })

    it.each<{ case: string; html: string }>([
        { case: 'nothing', html: '' },
        { case: 'no escaped character', html: 'plain text' },
        { case: 'every escaped character', html: `&<>"'` },
        { case: 'escaped characters between multi-byte ones', html: `é&ü<€>"😀'中` },
        { case: 'a lone surrogate beside an ampersand', html: '\ud800&' },
        { case: 'a body of ampersands', html: '&'.repeat(10_000) },
    ])('counts the escaped bytes of $case as escaping it would', ({ html }) => {
        expect(escapedHtmlByteLength(html)).toBe(Buffer.byteLength(escapeHtml(html), 'utf8'))
    })
})
