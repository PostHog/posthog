import {
    FakeSesEndpoint,
    SES_REJECTED,
    SES_SENDING_RATE,
    SES_SERVER_ERROR,
    SES_THROTTLE,
    SesReply,
} from './_tests/fake-ses-endpoint'
import { SES_SEND_TIMEOUT_MS } from './sandbox-deadlines'
import { SandboxMessage } from './sandbox-message'
import { SandboxSesClient, createSandboxSesV2Client } from './sandbox-ses-client'

describe('SandboxSesClient', () => {
    const message: SandboxMessage = {
        from: { address: 'sandbox@send.example.com', name: 'Acme "Labs" via PostHog' },
        to: { address: 'Member@Example.com' },
        subject: 'Hi',
        text: 'Hello',
        html: '<p>Hello</p>',
        headers: [{ name: 'X-PostHog-Organization-Id', value: 'org-1' }],
    }
    const tags = {
        teamId: 2,
        hogFlowId: '0190f0f0-0000-7000-8000-000000000001',
        invocationId: '0190f0f0-0000-7000-8000-000000000002',
        actionId: 'action_email_sandbox_1',
        flowVersion: 4,
        isTest: false,
    }
    const runTags = {
        ph_sbx_team: '2',
        ph_sbx_flow: tags.hogFlowId,
        ph_sbx_run: tags.invocationId,
        ph_sbx_action: 'action_email_sandbox_1',
        ph_sbx_version: '4',
        ph_sbx_test: 'false',
    }
    const parentRunId = '0190f0f0-0000-7000-8000-000000000003'

    let ses: FakeSesEndpoint
    let client: SandboxSesClient

    beforeEach(async () => {
        ses = new FakeSesEndpoint()
        const endpoint = await ses.start()
        client = new SandboxSesClient(createSandboxSesV2Client({ region: 'us-east-1', endpoint }), {
            configurationSet: 'sandbox-config-set',
            tenantName: 'sandbox-tenant',
        })
    })

    afterEach(async () => {
        await ses.stop()
    })

    it.each([
        ['a workflow run', tags, runTags],
        [
            'a batch-triggered run, with its parent run',
            { ...tags, parentRunId },
            { ...runTags, ph_sbx_parent_run: parentRunId },
        ],
    ])(
        'delivers one message to one To address through the sandbox configuration set and tenant, tagged with %s',
        async (_name, sendTags, emailTags) => {
            await expect(client.send(message, sendTags)).resolves.toEqual({ status: 'accepted', messageId: 'ses-1' })

            expect(ses.delivered).toEqual([
                {
                    messageId: 'ses-1',
                    from: { name: 'Acme "Labs" via PostHog', address: 'sandbox@send.example.com' },
                    to: [{ name: '', address: 'Member@Example.com' }],
                    cc: [],
                    bcc: [],
                    replyTo: [],
                    subject: 'Hi',
                    text: 'Hello',
                    html: '<p>Hello</p>',
                    headers: { 'X-PostHog-Organization-Id': 'org-1' },
                    tags: emailTags,
                    tenantName: 'sandbox-tenant',
                    configurationSet: 'sandbox-config-set',
                },
            ])
        }
    )

    it('delivers a sender and recipient name outside ASCII intact', async () => {
        await client.send(
            {
                ...message,
                from: { ...message.from, name: 'Zürich Café via PostHog' },
                to: { address: 'member@example.com', name: 'Ōta Jun' },
            },
            tags
        )

        expect(ses.delivered.map(({ from, to }) => ({ from, to }))).toEqual([
            {
                from: { name: 'Zürich Café via PostHog', address: 'sandbox@send.example.com' },
                to: [{ name: 'Ōta Jun', address: 'member@example.com' }],
            },
        ])
    })

    it.each<[string, SesReply, object]>([
        ['a throttle', SES_THROTTLE, { status: 'retry', reason: 'ses_throttled' }],
        ['a sending-rate limit', SES_SENDING_RATE, { status: 'retry', reason: 'ses_throttled' }],
        ['a server error', SES_SERVER_ERROR, { status: 'retry', reason: 'ses_transient' }],
        ['a dropped connection', { kind: 'drop' }, { status: 'retry', reason: 'ses_transient' }],
        ['an answer without a message id', { kind: 'accept-without-id' }, { status: 'retry', reason: 'ses_transient' }],
        ['a rejected message', SES_REJECTED, { status: 'failed', reason: 'ses_rejected' }],
    ])('reports %s after one attempt, with nothing delivered', async (_name, reply, expected) => {
        ses.replyAlways(reply)

        await expect(client.send(message, tags)).resolves.toEqual(expected)
        expect(ses.attempts).toBe(1)
        expect(ses.delivered).toEqual([])
    })

    it('gives up on a send SES never answers and retries it later', async () => {
        ses.replyAlways({ kind: 'hang' })
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        try {
            const result = client.send(message, tags)
            await jest.advanceTimersByTimeAsync(SES_SEND_TIMEOUT_MS)

            await expect(result).resolves.toEqual({ status: 'retry', reason: 'ses_transient' })
        } finally {
            jest.useRealTimers()
        }
    })
})
