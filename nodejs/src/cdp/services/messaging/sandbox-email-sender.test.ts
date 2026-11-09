import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { logger } from '~/common/utils/logger'
import { TeamManager } from '~/common/utils/team-manager'

import { RateLimiterService } from '../rate-limiter/rate-limiter.service'
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
        dailyTeamCap: 25,
        dailyRecipientCap: 5,
    },
    teamManager,
    blockedEventRedis,
    null
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
        ['at the end of a fragment', '<p>Hi</p>', `<p>Hi</p><div>${footer}</div>`],
    ])('adds the HTML footer %s', async (_case, html, expected) => {
        const { params: result } = await sender.buildSandboxMessage(params(html), 'Example organization via PostHog', 1)
        expect(result.html).toBe(expected)
    })
    it('escapes the sender name in the HTML footer', async () => {
        const { params: result } = await sender.buildSandboxMessage(params('<p>Hi</p>'), '<b>Tom</b> & "Jerry"', 1)
        expect(result.html).toContain('<div>This email was sent by &lt;b&gt;Tom&lt;/b&gt; &amp; &quot;Jerry&quot; with')
    })
    it('puts the preview text after the opening body tag', async () => {
        const { params: result } = await sender.buildSandboxMessage(
            params('<body><p>Hi</p></body>', undefined, 'Tom &amp; Jerry'),
            'Example organization via PostHog',
            1
        )
        expect(result.html).toMatch(/^<body><span style="display:none[^"]*">Tom &amp; Jerry<\/span><p>Hi<\/p><div>/)
        expect(result.preheader).toBeUndefined()
    })
    it('sends from the fixed address, drops the reply-to and adds the footer to the text part', async () => {
        const { params: result } = await sender.buildSandboxMessage(
            { ...params('', 'Hello'), replyTo: 'replies@example.org' },
            'Example organization via PostHog',
            1
        )
        expect(result).toMatchObject({
            from: { name: 'Example organization via PostHog', email: 'fixed-sandbox@example.com' },
            text: `Hello\n\n${footer}`,
        })
        expect(result.replyTo).toBeUndefined()
        expect(result.html).toBe('')
    })
    it('refuses an email without HTML or text content', async () => {
        await expect(sender.buildSandboxMessage(params(''), 'Example organization via PostHog', 1)).rejects.toThrow(
            'The sandbox email template must include HTML or text content. Update the template and try again.'
        )
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
            blockedEventRedis,
            null
        )
        const { params: result } = await paddedSender.buildSandboxMessage(
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
    it.each([
        ['switched on with an empty route setting', { enabled: true, configurationSetName: '  ' }],
        ['switched off', { enabled: false }],
    ])('cannot send when %s', (_case, overrides) => {
        expect(
            new SandboxEmailSender({ ...sender.config, ...overrides }, teamManager, blockedEventRedis, null).canSend
        ).toBe(false)
    })
    it.each([
        ['logs nothing on a consumer that has no daily cap pool', null, 25, 0],
        ['logs an error when a daily cap is unusable', {} as RateLimiterService, 0, 1],
    ])('%s', (_case, dailyCapLimiter, dailyTeamCap, errors) => {
        const error = jest.spyOn(logger, 'error').mockImplementation(() => undefined)
        try {
            new SandboxEmailSender({ ...sender.config, dailyTeamCap }, teamManager, blockedEventRedis, dailyCapLimiter)
            expect(error).toHaveBeenCalledTimes(errors)
        } finally {
            error.mockRestore()
        }
    })
})
