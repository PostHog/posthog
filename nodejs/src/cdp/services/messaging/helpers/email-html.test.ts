import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { defaultConfig } from '~/common/config/config'

import { htmlForSes, htmlForSesMaxBytes, tagEmailLinks } from './email-html'
import { EmailTrackingCodeSigner } from './tracking-code'

const SITE_URL = 'https://us.posthog.com'
const RUN_ID = '01890a5d-ac0f-7000-8000-000000000000'
const UTM = {
    tags: { utm_source: 'posthog', utm_medium: 'email', utm_campaign: 'Spring sale', utm_content: 'cta' },
    siteUrl: SITE_URL,
    fixedScanner: true,
}

describe('htmlForSesMaxBytes', () => {
    const tracking = {
        invocation: createExampleInvocation(),
        signer: new EmailTrackingCodeSigner(defaultConfig.ENCRYPTION_SALT_KEYS, 'https://track.example.com'),
        isTest: false,
    }

    it.each<{ case: string; html: string; utm?: null }>([
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
        { case: 'entity-encoded characters', html: '<a href="https://example.com/?a=&#x22;&#39;&lt;">x</a>' },
        { case: 'padding whitespace', html: '<a href="  https://example.com/p  ">x</a>' },
        { case: 'an earlier run id', html: '<a href="https://example.com/?ph_workflow_run=old&amp;a=1">x</a>' },
        { case: 'a body tag inside the href', html: '<a href="https://example.com/?q=</body>">x</a></body>' },
        {
            case: 'many links with an existing SES tag',
            html: `<body>${'<a ses:tags="k:v" href="https://example.com/?x=\'">y</a>'.repeat(12)}</body>`,
        },
    ])('bounds the bytes SES gets for $case', ({ html, utm = UTM }) => {
        const sent = htmlForSes(
            tagEmailLinks(html, utm, { runId: RUN_ID, senderEmail: 'hi@example.com', siteUrl: SITE_URL }),
            tracking,
            'Your files are attached'
        )

        expect(Buffer.byteLength(sent, 'utf8')).toBeLessThanOrEqual(
            htmlForSesMaxBytes(html, utm, RUN_ID, tracking, 'Your files are attached')
        )
    })
})
