import { createMockJobQueue } from '~/tests/helpers/mocks/job-queue.mock'

import { closeHub, createHub } from '~/common/utils/db/hub'
import { createCdpConsumerDeps } from '~/tests/helpers/cdp'

import { Hub } from '../../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CdpCyclotronWorkerEmail } from './cdp-cyclotron-worker-email.consumer'

jest.setTimeout(5000)

describe('CdpCyclotronWorkerEmail', () => {
    let hub: Hub

    beforeAll(async () => {
        hub = await createHub()
    })

    afterAll(async () => {
        await closeHub(hub)
    })

    it('should set queue to email', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['queue']).toBe('email')
    })

    it('should extend CdpCyclotronWorkerHogFlow', () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        expect(worker['name']).toBe('CdpCyclotronWorkerEmail')
    })

    it('persists an independent capture job before acknowledging a sent email', async () => {
        const queue = createMockJobQueue()
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), queue)
        const invocation = {
            id: 'invocation-example',
            teamId: 1,
            functionId: 'workflow-example',
            state: null,
            queue: 'email' as const,
            queuePriority: 0,
        }
        const result = createInvocationResult(invocation)
        result.conversationCaptures = [
            {
                source_id: invocation.id,
                provider_message_id: '010001-example-000000',
                email_integration_id: 1,
                sent_at: new Date().toISOString(),
                sender: { email: 'agent@example.com', name: 'Agent' },
                to: { email: 'customer@example.net', name: 'Customer' },
                cc: [],
                subject: 'Example subject',
                body_plain: 'Example body',
            },
        ]

        await worker['queueInvocationResults']([result])

        const job = queue.queueInvocations.mock.calls[0][0][0]
        expect(job.queue).toBe('email')
        expect(job.id).not.toBe(invocation.id)
        expect(job.queueParameters?.type).toBe('emailCapture')
        expect(job.queueParameters).not.toHaveProperty('bcc')
        expect(queue.queueInvocations.mock.invocationCallOrder[0]).toBeLessThan(
            queue.queueInvocationResults.mock.invocationCallOrder[0]
        )

        queue.queueInvocations.mockRejectedValueOnce(new Error('queue unavailable'))
        const skipSpy = jest.spyOn(worker.emailService, 'recordConversationCaptureSkipped').mockResolvedValue(undefined)
        await expect(worker['queueInvocationResults']([result])).resolves.toBeUndefined()
        expect(queue.queueInvocationResults).toHaveBeenCalledTimes(2)
        expect(skipSpy).toHaveBeenCalledWith(1, 'invocation-example', 'queue_unavailable')
    })

    it('routes a retrying capture job without invoking the email send path', async () => {
        const worker = new CdpCyclotronWorkerEmail(hub, createCdpConsumerDeps(hub), createMockJobQueue())
        const invocation = {
            id: 'capture-example',
            teamId: 1,
            functionId: 'workflow-example',
            state: null,
            queue: 'email' as const,
            queuePriority: 0,
            queueParameters: {
                type: 'emailCapture' as const,
                attempts: 1,
                capture: {
                    source_id: 'invocation-example',
                    provider_message_id: '010001-example-000000',
                    email_integration_id: 1,
                    sent_at: new Date().toISOString(),
                    sender: { email: 'agent@example.com', name: 'Agent' },
                    to: { email: 'customer@example.net', name: 'Customer' },
                    cc: [],
                    subject: 'Example subject',
                    body_plain: 'Example body',
                },
            },
        }
        const captureResult = createInvocationResult(
            invocation,
            { queueParameters: invocation.queueParameters },
            { finished: false }
        )
        const captureSpy = jest
            .spyOn(worker.emailService, 'executeConversationCapture')
            .mockResolvedValue(captureResult)
        const sendSpy = jest.spyOn(worker.emailService, 'executeSendEmail')

        const results = await worker.processInvocations([invocation])

        expect(results).toEqual([captureResult])
        expect(captureSpy).toHaveBeenCalledTimes(1)
        expect(sendSpy).not.toHaveBeenCalled()
    })
})
