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
            eventName?: string
            notifyUserIds?: unknown
            actionId?: string
            isTest?: boolean
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
        invocation.state.globals.event.event = options.eventName ?? '$data_warehouse_sync_failure_digest'
        invocation.state.globals.event.properties =
            'notifyUserIds' in options ? { $notify_user_ids: options.notifyUserIds } : { $notify_user_ids: [memberId] }
        invocation.state.actionId = options.actionId
        invocation.state.vmState = { stack: [] } as any

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation)
        await getAsyncFunctionHandler('sendSystemEmail')!.execute(
            [options.args ?? { subject: 'Sync failed', body: 'The sync failed.' }],
            {
                systemEmailService: service,
                isTest: options.isTest,
                consumeInlineAsyncBudget: () => {},
            } as unknown as AsyncFunctionContext,
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
            subject: 'Sync failed',
        })
        expect(result.metrics).toMatchObject([{ metric_kind: 'email', metric_name: 'email_sent', count: 2 }])
        expect(result.invocation.queueParameters).toBeUndefined()
        expect(result.invocation.queue).toEqual('hog')
    })

    it('sends to every resolved member in one call', async () => {
        const members = await Promise.all(Array.from({ length: 60 }, () => createMember(organizationId)))

        const { response, result } = await send({ notifyUserIds: members.map((member) => member.id) })

        expect(response).toEqual({ success: true })
        expect(transport.send.mock.calls.map(([message]) => message.to).sort()).toEqual(
            members.map((member) => member.email).sort()
        )
        expect(result.metrics).toMatchObject([{ metric_name: 'email_sent', count: 60 }])
    })

    test.each([
        ['a plain destination', { hogFunction: { type: 'destination' as const } }, undefined],
        ['another template', { hogFunction: { template_id: 'template-webhook' } }, undefined],
        ['a function without a template', { hogFunction: { template_id: undefined } }, undefined],
        ['a workflow step', { actionId: 'action_1' }, undefined],
        ['an event outside the allowlist', { eventName: '$pageview' }, "This alert can't send email for this event."],
        ['a team outside the allowlist', { config: { enabledTeams: '' } }, undefined],
        ['an instance without a sender address', { config: { fromAddress: '' } }, undefined],
        ['a missing subject', { args: { body: 'The sync failed.' } }, undefined],
        ['an empty body', { args: { subject: 'Sync failed', body: '  ' } }, undefined],
        ['arguments that are not an object', { args: 'Sync failed' }, undefined],
    ])('sends nothing for %s', async (_name, options, error) => {
        const { response, result } = await send(options)

        expect(response).toEqual({ success: false, error: error ?? expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
        expect(metricNames(result)).toEqual(['email_failed'])
    })

    it('sends nothing from a test run, where the caller supplies the recipients', async () => {
        const { response } = await send({ isTest: true })

        expect(response).toEqual({ success: false, error: expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
    })

    test.each([
        ['no $notify_user_ids property', undefined],
        ['an empty list', []],
        ['ids that match no user', [2_147_000_001]],
        ['values that are not user ids', ['1', null, -1, 1.5, { id: 1 }]],
        ['a value that is not a list', 'all'],
    ])('skips the send for %s', async (_name, notifyUserIds) => {
        const { response, result } = await send({ notifyUserIds })

        expect(response).toEqual({ success: false, error: expect.any(String) })
        expect(transport.send).not.toHaveBeenCalled()
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

    it('escapes HTML, strips header breaks and sends the full subject and body', async () => {
        const longSubject = 's'.repeat(201)
        const longBody = 'b'.repeat(4001)
        const markup = ['<script>alert("x")</script>', '<a href="https://example.org">link</a>']
        await send({
            args: {
                subject: `Failed\r\nBcc: target@example.org ${longSubject}`,
                body: [markup.join('\r\n'), longBody].join(''),
                action_url: `${SITE_URL}/project/${teamId}/pipeline`,
                action_label: '<img src=x>',
            },
        })

        const { subject, html, text } = transport.send.mock.calls[0][0]
        expect(subject).not.toMatch(/[\r\n]/)
        expect(subject).toEqual(`Failed Bcc: target@example.org ${longSubject}`)
        expect(html).toContain('&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;<br>&lt;a href=')
        expect(html).not.toMatch(/<script|<img|<a href="https:\/\/example\.org/)
        expect(html).toContain('&lt;img src=x&gt;</a>')
        expect(html).toContain('Web &lt;b&gt;shop&lt;/b&gt;')
        expect(html).toContain('Sync &lt;failures&gt;')
        expect(html).toContain(longBody)
        expect(text).toContain('<script>alert("x")</script>')
        expect(text).toContain([markup.join('\n'), longBody].join(''))
    })

    test.each([
        [
            'a page in this project with a label',
            (id: number) => `${SITE_URL}/project/${id}/functions/abc?tab=logs`,
            'Open alert',
            true,
        ],
        [
            'a page in this project with an empty label',
            (id: number) => `${SITE_URL}/project/${id}/functions/abc`,
            '',
            false,
        ],
        ['another project', (id: number) => `${SITE_URL}/project/${id + 1}/functions/abc`, 'Open alert', false],
        [
            'a project id that only shares a prefix',
            (id: number) => `${SITE_URL}/project/${id}0/functions`,
            'Open alert',
            false,
        ],
        ['another host', (id: number) => `https://example.org/project/${id}/functions`, 'Open alert', false],
        [
            'a host that only shares a prefix',
            (id: number) => `${SITE_URL}.example.org/project/${id}/`,
            'Open alert',
            false,
        ],
        [
            'a path that climbs out of the project',
            (id: number) => `${SITE_URL}/project/${id}/../../logout`,
            'Open alert',
            false,
        ],
        ['a script URL', () => 'javascript:alert(1)', 'Open alert', false],
        ['a value that is not a string', () => ({ href: SITE_URL }), 'Open alert', false],
    ])('renders the button only for a valid link and label: %s', async (_name, buildUrl, actionLabel, kept) => {
        const actionUrl = buildUrl(teamId)

        await send({
            args: {
                subject: 'Sync failed',
                body: 'The sync failed.',
                action_url: actionUrl,
                action_label: actionLabel,
            },
        })

        const { html, text } = transport.send.mock.calls[0][0]
        expect(html.includes('>Open alert</a>')).toEqual(kept)
        expect(text.includes('Open alert:')).toEqual(kept)
        if (!kept && typeof actionUrl === 'string') {
            expect(html).not.toContain(actionUrl)
            expect(text).not.toContain(actionUrl)
        }
    })

    test.each([
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
})
