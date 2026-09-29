import { CyclotronJobInvocation } from '~/cdp/types'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { captureTeamEvent } from '~/common/utils/posthog'
import { internalFetch } from '~/common/utils/request'
import { TeamManager } from '~/common/utils/team-manager'

import { WorkflowConversationCaptureService } from './workflow-conversation-capture.service'

jest.mock('~/common/utils/request', () => ({ internalFetch: jest.fn() }))
jest.mock('~/common/utils/posthog', () => ({ captureTeamEvent: jest.fn() }))

const mockInternalFetch = jest.mocked(internalFetch)

const capture = {
    source_id: 'invocation-example',
    provider_message_id: '010001-example-000000',
    email_integration_id: 1,
    sent_at: '2026-09-28T12:00:00.000Z',
    sender: { email: 'agent@example.com', name: 'Agent' },
    to: { email: 'customer@example.net', name: 'Customer' },
    cc: [],
    subject: 'Example subject',
    body_plain: 'Example text',
}

const createCaptureInvocation = (attempts = 0): CyclotronJobInvocation => ({
    id: 'capture-job-example',
    teamId: 1,
    functionId: 'workflow-example',
    state: null,
    queue: 'email',
    queuePriority: 0,
    queueParameters: { type: 'emailCapture', capture, attempts },
})

describe('WorkflowConversationCaptureService', () => {
    let service: WorkflowConversationCaptureService
    let teamManager: Pick<TeamManager, 'getTeam'>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2026-09-28T12:00:00.000Z'))
        teamManager = { getTeam: jest.fn().mockResolvedValue({ id: 1, organization_id: 'org-example' }) }
        service = new WorkflowConversationCaptureService(
            teamManager as TeamManager,
            new ScopedServiceJwt(PosthogJwtAudience.CONVERSATIONS_WORKFLOW_EMAILS, 'test-only-secret'),
            'http://internal.example'
        )
        mockInternalFetch.mockReset()
        jest.mocked(captureTeamEvent).mockClear()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('records an unmatched send without retrying SES', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ status: 'skipped_unmatched' }),
        } as any)
        const result = await service.executeCapture(createCaptureInvocation())
        await Promise.resolve()
        expect(result.finished).toBe(true)
        expect(captureTeamEvent).toHaveBeenCalledWith(
            expect.objectContaining({ id: 1 }),
            'workflow_conversation_capture_skipped',
            { reason: 'unmatched_after_send', invocation_id: capture.source_id }
        )
    })

    it.each([
        [0, 2000],
        [12, 30 * 60 * 1000],
    ])(
        'retries the capture job with backoff after %s attempts when the API is unavailable',
        async (attempts, delay) => {
            mockInternalFetch.mockRejectedValue(new Error('unavailable'))
            const result = await service.executeCapture(createCaptureInvocation(attempts))
            expect(result.finished).toBe(false)
            expect(result.invocation.queueParameters).toEqual({ type: 'emailCapture', capture, attempts: attempts + 1 })
            expect(result.invocation.queueScheduledAt?.toMillis()).toBe(Date.now() + delay)
            expect(result.skipMonitoring).toBe(true)
        }
    )
})
