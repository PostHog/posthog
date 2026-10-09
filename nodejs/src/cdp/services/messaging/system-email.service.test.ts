import { createExampleInvocation } from '~/cdp/_tests/fixtures'
import { AsyncFunctionContext, getAsyncFunctionHandler } from '~/cdp/async-function-registry'
import '~/cdp/async-functions/send-system-email'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, HogFunctionType } from '~/cdp/types'
import { createInvocationResult } from '~/cdp/utils/invocation-utils'
import { defaultConfig } from '~/common/config/config'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import {
    createOrganization,
    createOrganizationMembership,
    createTeam,
    insertRow,
    uniqueTestId,
} from '~/tests/helpers/sql'

import {
    SYSTEM_EMAIL_MAX_BODY_LENGTH,
    SYSTEM_EMAIL_MAX_SUBJECT_LENGTH,
    SYSTEM_EMAIL_TEMPLATE_ID,
    SystemEmailMessage,
    SystemEmailResult,
    SystemEmailService,
    SystemEmailServiceConfig,
} from './system-email.service'

const SITE_URL = 'https://app.example.com'

describe('SystemEmailService', () => {
    let postgres: PostgresRouter
    let teamId: number
    let organizationId: string
    let memberId: number
    let memberEmail: string

    const transport = { send: jest.fn<Promise<void>, [SystemEmailMessage]>() }
    const rateLimiter = { claimAllOrNothingPair: jest.fn() }
    const teamWorkflowsConfigService = { getEmailSendingSuspension: jest.fn() }

    const createUser = async (overrides: Record<string, unknown> = {}): Promise<{ id: number; email: string }> => {
        const uuid = new UUIDT().toString()
        const user = await insertRow(postgres, 'posthog_user', {
            id: uniqueTestId(),
            uuid,
            password: 'gibberish',
            first_name: 'Test',
            last_name: 'User',
            email: `${uuid}@example.com`,
            distinct_id: uuid,
            is_staff: false,
            is_active: true,
            date_joined: new Date().toISOString(),
            events_column_config: { active: 'DEFAULT' },
            ...overrides,
        })
        return { id: user.id, email: user.email }
    }

    const createMember = async (
        memberOrganizationId: string,
        overrides: Record<string, unknown> = {}
    ): Promise<{ id: number; email: string }> => {
        const user = await createUser(overrides)
        await createOrganizationMembership(postgres, memberOrganizationId, user.id)
        return user
    }

    const send = async (
        options: {
            args?: unknown
            hogFunction?: Partial<HogFunctionType>
            notifyUserIds?: unknown
            actionId?: string
            config?: Partial<SystemEmailServiceConfig>
        } = {}
    ): Promise<{
        response: SystemEmailResult
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    }> => {
        const service = new SystemEmailService(
            {
                enabledTeams: String(teamId),
                fromAddress: 'alerts@mail.example.com',
                fromName: 'PostHog',
                replyTo: 'no-reply@mail.example.com',
                siteUrl: SITE_URL,
                ...options.config,
            },
            {
                postgres,
                teamManager: {
                    getTeam: () =>
                        Promise.resolve({ id: teamId, organization_id: organizationId, name: 'Web <b>shop</b>' }),
                } as any,
                teamWorkflowsConfigService: teamWorkflowsConfigService as any,
                rateLimiter: rateLimiter as any,
                transport,
            }
        )

        const invocation = createExampleInvocation({
            team_id: teamId,
            type: 'internal_destination',
            template_id: SYSTEM_EMAIL_TEMPLATE_ID,
            name: 'Sync <failures>',
            ...options.hogFunction,
        })
        invocation.state.globals.event.properties =
            'notifyUserIds' in options ? { $notify_user_ids: options.notifyUserIds } : { $notify_user_ids: [memberId] }
        invocation.state.actionId = options.actionId
        invocation.state.vmState = { stack: [] } as any

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation)
        await getAsyncFunctionHandler('sendSystemEmail')!.execute(
            [options.args ?? { subject: 'Sync failed', body: 'The sync failed.' }],
            { systemEmailService: service, consumeInlineAsyncBudget: () => {} } as unknown as AsyncFunctionContext,
            result
        )

        return { response: result.invocation.state.vmState!.stack[0], result }
    }

    const metricNames = (result: CyclotronJobInvocationResult): string[] => result.metrics.map((m) => m.metric_name)

    beforeAll(async () => {
        postgres = new PostgresRouter(defaultConfig)
        organizationId = await createOrganization(postgres)
        teamId = await createTeam(postgres, organizationId)
        const member = await createMember(organizationId)
        memberId = member.id
        memberEmail = member.email
    })

    afterAll(async () => {
        await postgres.end()
    })

    beforeEach(() => {
        transport.send.mockReset().mockResolvedValue(undefined)
        rateLimiter.claimAllOrNothingPair
            .mockReset()
            .mockResolvedValue({ granted: true, deniedIndex: null, retryAfterMs: null, reserved: false })
        teamWorkflowsConfigService.getEmailSendingSuspension.mockReset().mockResolvedValue(null)
    })

    it('sends one message per recipient from the configured sender and stays off the email queue', async () => {
        const second = await createMember(organizationId)

        const { response, result } = await send({ notifyUserIds: [memberId, second.id, memberId] })

        expect(response).toEqual({ success: true })
        expect(transport.send.mock.calls.map(([message]) => message.to).sort()).toEqual(
            [memberEmail, second.email].sort()
        )
        expect(transport.send.mock.calls[0][0]).toMatchObject({
            from: { email: 'alerts@mail.example.com', name: 'PostHog' },
            replyTo: 'no-reply@mail.example.com',
            subject: '[PostHog] Sync failed',
        })
        expect(result.metrics).toMatchObject([{ metric_kind: 'email', metric_name: 'email_sent', count: 2 }])
        expect(result.invocation.queueParameters).toBeUndefined()
        expect(result.invocation.queue).toEqual('hog')
    })

    it.each([
        ['a plain destination', { hogFunction: { type: 'destination' as const } }],
        ['another template', { hogFunction: { template_id: 'template-webhook' } }],
        ['a function without a template', { hogFunction: { template_id: undefined } }],
        ['a workflow step', { actionId: 'action_1' }],
        ['a team outside the allowlist', { config: { enabledTeams: '' } }],
        ['an instance without a sender address', { config: { fromAddress: '' } }],
        ['a missing subject', { args: { body: 'The sync failed.' } }],
        ['an empty body', { args: { subject: 'Sync failed', body: '  ' } }],
        ['arguments that are not an object', { args: 'Sync failed' }],
    ])('sends nothing for %s', async (_name, options) => {
        const { response, result } = await send(options)

        expect(response).toEqual({ success: false, error: expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
        expect(rateLimiter.claimAllOrNothingPair).not.toHaveBeenCalled()
        expect(metricNames(result)).toEqual(['email_failed'])
    })

    it.each([
        ['no $notify_user_ids property', undefined],
        ['an empty list', []],
        ['ids that match no user', [2_147_000_001]],
        ['values that are not user ids', ['1', null, -1, 1.5, { id: 1 }]],
        ['a value that is not a list', 'all'],
    ])('skips the send for %s', async (_name, notifyUserIds) => {
        const { response, result } = await send({ notifyUserIds })

        expect(response).toEqual({ success: false, error: expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
        expect(rateLimiter.claimAllOrNothingPair).not.toHaveBeenCalled()
        expect(metricNames(result)).toEqual(['skipped_no_recipients'])
    })

    it('drops users from another organization, users without a membership and inactive users', async () => {
        const otherOrganizationId = await createOrganization(postgres)
        const outsider = await createMember(otherOrganizationId)
        const noMembership = await createUser()
        const inactive = await createMember(organizationId, { is_active: false })

        const { response } = await send({ notifyUserIds: [outsider.id, noMembership.id, inactive.id, memberId] })

        expect(response).toEqual({ success: true })
        expect(transport.send.mock.calls.map(([message]) => message.to)).toEqual([memberEmail])
    })

    it('ignores recipient and sender arguments from the hog call', async () => {
        await send({
            args: {
                subject: 'Sync failed',
                body: 'The sync failed.',
                to: 'target@example.org',
                cc: 'target@example.org',
                bcc: 'target@example.org',
                from: { email: 'ceo@example.org', name: 'CEO' },
                replyTo: 'target@example.org',
                recipients: ['target@example.org'],
            },
        })

        expect(transport.send).toHaveBeenCalledTimes(1)
        const message = transport.send.mock.calls[0][0]
        expect(message.to).toEqual(memberEmail)
        expect(message.from.email).toEqual('alerts@mail.example.com')
        expect(message.replyTo).toEqual('no-reply@mail.example.com')
        expect(JSON.stringify(message)).not.toContain('example.org')
    })

    it('escapes HTML, strips header breaks from the subject and caps the subject and body', async () => {
        await send({
            args: {
                subject: `Failed\r\nBcc: target@example.org ${'s'.repeat(SYSTEM_EMAIL_MAX_SUBJECT_LENGTH)}`,
                body: `<script>alert("x")</script>\n<a href="https://example.org">link</a>${'b'.repeat(SYSTEM_EMAIL_MAX_BODY_LENGTH)}`,
                action_url: `${SITE_URL}/project/${teamId}/pipeline`,
                action_label: '<img src=x>',
            },
        })

        const { subject, html, text } = transport.send.mock.calls[0][0]
        expect(subject).not.toMatch(/[\r\n]/)
        expect(subject).toHaveLength('[PostHog] '.length + SYSTEM_EMAIL_MAX_SUBJECT_LENGTH)
        expect(html).toContain('&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;<br>&lt;a href=')
        expect(html).not.toMatch(/<script|<img|<a href="https:\/\/example\.org/)
        expect(html).toContain('&lt;img src=x&gt;</a>')
        expect(html).toContain('Web &lt;b&gt;shop&lt;/b&gt;')
        expect(html).toContain('Sync &lt;failures&gt;')
        expect(html).not.toContain('b'.repeat(SYSTEM_EMAIL_MAX_BODY_LENGTH))
        expect(text).toContain('<script>alert("x")</script>')
        expect(text).not.toContain('b'.repeat(SYSTEM_EMAIL_MAX_BODY_LENGTH))
    })

    it.each([
        ['a page in this project', (id: number) => `${SITE_URL}/project/${id}/functions/abc?tab=logs`, true],
        ['another project', (id: number) => `${SITE_URL}/project/${id + 1}/functions/abc`, false],
        ['a project id that only shares a prefix', (id: number) => `${SITE_URL}/project/${id}0/functions`, false],
        ['another host', (id: number) => `https://example.org/project/${id}/functions`, false],
        ['a host that only shares a prefix', (id: number) => `${SITE_URL}.example.org/project/${id}/`, false],
        ['a path that climbs out of the project', (id: number) => `${SITE_URL}/project/${id}/../../logout`, false],
        ['a script URL', () => 'javascript:alert(1)', false],
        ['a value that is not a string', () => ({ href: SITE_URL }), false],
    ])('renders the button only for a link inside this project: %s', async (_name, buildUrl, kept) => {
        const actionUrl = buildUrl(teamId)

        await send({ args: { subject: 'Sync failed', body: 'The sync failed.', action_url: actionUrl } })

        const { html, text } = transport.send.mock.calls[0][0]
        expect(html.includes('Open in PostHog')).toEqual(kept)
        expect(text.includes('Open in PostHog')).toEqual(kept)
        if (!kept && typeof actionUrl === 'string') {
            expect(html).not.toContain(actionUrl)
        }
    })

    it.each([
        ['the hourly limit', { granted: false, deniedIndex: 0, retryAfterMs: 1000, reserved: false }],
        ['the daily limit', { granted: false, deniedIndex: 1, retryAfterMs: 1000, reserved: false }],
        ['a limiter failure', { granted: false, deniedIndex: null, retryAfterMs: null, reserved: false }],
    ])('blocks the send and reports it on %s', async (_name, claim) => {
        rateLimiter.claimAllOrNothingPair.mockResolvedValue(claim)

        const { response, result } = await send()

        expect(response).toEqual({ success: false, error: expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
        expect(metricNames(result)).toEqual(['email_rate_limited'])
        expect(result.invocation.queueScheduledAt).toBeUndefined()
    })

    it.each([
        ['staff', false],
        ['provider', true],
    ])('honors only the staff suspension: %s', async (cause, sent) => {
        teamWorkflowsConfigService.getEmailSendingSuspension.mockResolvedValue(cause)

        const { response } = await send()

        expect(response.success).toEqual(sent)
        expect(transport.send).toHaveBeenCalledTimes(sent ? 1 : 0)
    })

    it('returns a failure without throwing when the transport rejects a recipient', async () => {
        const second = await createMember(organizationId)
        transport.send.mockImplementation((message) =>
            message.to === second.email
                ? Promise.reject(new Error(`Rejected address ${second.email}`))
                : Promise.resolve()
        )

        const { response, result } = await send({ notifyUserIds: [memberId, second.id] })

        expect(response.success).toEqual(false)
        expect(response.error).not.toContain(second.email)
        expect(result.metrics).toMatchObject([
            { metric_name: 'email_sent', count: 1 },
            { metric_name: 'email_failed', count: 1 },
        ])
        expect(result.logs.map((log) => log.message).join(' ')).not.toContain('@')
    })

    it('returns a failure without throwing when a dependency throws', async () => {
        rateLimiter.claimAllOrNothingPair.mockRejectedValue(new Error('connection reset'))

        const { response, result } = await send()

        expect(response).toEqual({ success: false, error: expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
        expect(metricNames(result)).toEqual(['email_failed'])
    })
})
