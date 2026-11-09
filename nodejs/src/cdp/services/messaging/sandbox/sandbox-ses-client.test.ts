import { SendEmailCommand } from '@aws-sdk/client-sesv2'

import { SandboxMessage } from './sandbox-message'
import { SES_SEND_TIMEOUT_MS, SandboxSesClient, createSandboxSesV2Client } from './sandbox-ses-client'

describe('SandboxSesClient', () => {
    const message: SandboxMessage = {
        from: { address: 'sandbox@send.example.com', name: 'Acme via PostHog' },
        to: { address: 'Member@Example.com' },
        subject: 'Hi',
        text: 'Hello',
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
    const settings = { configurationSet: 'sandbox-config-set', tenantName: 'sandbox-tenant' }

    const runTags = [
        { Name: 'ph_sbx_team', Value: '2' },
        { Name: 'ph_sbx_flow', Value: tags.hogFlowId },
        { Name: 'ph_sbx_run', Value: tags.invocationId },
        { Name: 'ph_sbx_action', Value: 'action_email_sandbox_1' },
        { Name: 'ph_sbx_version', Value: '4' },
        { Name: 'ph_sbx_test', Value: 'false' },
    ]
    const parentRunId = '0190f0f0-0000-7000-8000-000000000003'

    it.each([
        ['a workflow run', tags, runTags],
        [
            'a batch-triggered run, with its parent run',
            { ...tags, parentRunId },
            [...runTags, { Name: 'ph_sbx_parent_run', Value: parentRunId }],
        ],
    ])(
        'sends to one To address through the sandbox configuration set and tenant, tagged with %s',
        async (_name, sendTags, emailTags) => {
            const send = jest.fn().mockResolvedValue({ MessageId: 'ses-1' })

            await expect(new SandboxSesClient({ send }, settings).send(message, sendTags)).resolves.toEqual({
                status: 'accepted',
                messageId: 'ses-1',
            })

            const command: SendEmailCommand = send.mock.calls[0][0]
            expect(command.input).toMatchObject({
                FromEmailAddress: '"Acme via PostHog" <sandbox@send.example.com>',
                Destination: { ToAddresses: ['Member@Example.com'] },
                ConfigurationSetName: 'sandbox-config-set',
                TenantName: 'sandbox-tenant',
            })
            expect(command.input.EmailTags).toEqual(emailTags)
            expect(command.input.Destination).not.toHaveProperty('CcAddresses')
            expect(command.input.Destination).not.toHaveProperty('BccAddresses')
            expect(command.input).not.toHaveProperty('ReplyToAddresses')
        }
    )

    const sesError = (name: string, httpStatusCode?: number): Error =>
        Object.assign(new Error(name), { name, $metadata: { httpStatusCode } })

    it.each([
        ['a throttle', sesError('ThrottlingException', 400), { status: 'retry', reason: 'ses_throttled' }],
        [
            'a sending-rate limit',
            sesError('TooManyRequestsException', 429),
            { status: 'retry', reason: 'ses_throttled' },
        ],
        ['a server error', sesError('InternalFailure', 500), { status: 'retry', reason: 'ses_transient' }],
        ['a network error', sesError('TimeoutError'), { status: 'retry', reason: 'ses_transient' }],
        ['a rejected message', sesError('MessageRejected', 400), { status: 'failed', reason: 'ses_rejected' }],
    ])('classifies %s', async (_name, error, expected) => {
        const send = jest.fn().mockRejectedValue(error)

        await expect(new SandboxSesClient({ send }, settings).send(message, tags)).resolves.toEqual(expected)
    })

    it('gives up on a send SES never answers and retries it later', async () => {
        jest.useFakeTimers()
        try {
            const send = jest.fn(
                (_command: SendEmailCommand, options: { abortSignal: AbortSignal }) =>
                    new Promise((_resolve, reject) =>
                        options.abortSignal.addEventListener('abort', () =>
                            reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
                        )
                    )
            )
            const result = new SandboxSesClient({ send } as any, settings).send(message, tags)

            await jest.advanceTimersByTimeAsync(SES_SEND_TIMEOUT_MS)

            await expect(result).resolves.toEqual({ status: 'retry', reason: 'ses_transient' })
        } finally {
            jest.useRealTimers()
        }
    })

    it('builds an SDK client that never retries a send by itself', async () => {
        const client = createSandboxSesV2Client({ region: 'us-east-1', endpoint: '' })

        await expect(client.config.maxAttempts()).resolves.toBe(1)
    })
})
