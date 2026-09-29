import { CyclotronInvocationQueueParametersEmailType } from '~/cdp/schema/cyclotron'
import { CyclotronJobInvocation } from '~/cdp/types'
import { PosthogJwtAudience } from '~/cdp/utils/jwt-utils'
import { ScopedServiceJwt } from '~/cdp/utils/scoped-service-jwt'
import { parseJSON } from '~/common/utils/json-parse'
import { captureTeamEvent, isFeatureFlagEnabled } from '~/common/utils/posthog'
import { internalFetch } from '~/common/utils/request'
import { TeamManager } from '~/common/utils/team-manager'

import { ELIGIBILITY_TIMEOUT_MS, WorkflowConversationCaptureService } from './workflow-conversation-capture.service'

jest.mock('~/common/utils/request', () => ({ internalFetch: jest.fn() }))
jest.mock('~/common/utils/posthog', () => ({
    isFeatureFlagEnabled: jest.fn(),
    captureTeamEvent: jest.fn(),
}))

const mockInternalFetch = jest.mocked(internalFetch)
const mockFlag = jest.mocked(isFeatureFlagEnabled)

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

const emailParams = (): CyclotronInvocationQueueParametersEmailType => ({
    type: 'email',
    from: { integrationId: 1 },
    to: { email: 'customer@example.net' },
    subject: 'Example subject',
    text: 'Example text',
    html: '<p>Example text</p>',
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
        mockFlag.mockReset()
        jest.mocked(captureTeamEvent).mockClear()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('caps the pre-send wait at two minutes from the first failed lookup', () => {
        const params = emailParams()
        expect(service.getEligibilityDelay(params)).toBe(10000)
        const firstFailureAt = params.conversationEligibilityFirstFailedAt
        jest.advanceTimersByTime(ELIGIBILITY_TIMEOUT_MS - 1000)
        expect(service.getEligibilityDelay(params)).toBe(1000)
        jest.advanceTimersByTime(1000)
        expect(service.getEligibilityDelay(params)).toBeNull()
        expect(params.conversationEligibilityFirstFailedAt).toBe(firstFailureAt)
    })

    it('does not delay sends before the dedicated JWT key is provisioned', async () => {
        const unconfigured = new WorkflowConversationCaptureService(
            teamManager as TeamManager,
            new ScopedServiceJwt(PosthogJwtAudience.CONVERSATIONS_WORKFLOW_EMAILS, ''),
            'http://internal.example'
        )
        const result = await unconfigured.checkEligibility(
            1,
            capture.source_id,
            capture.email_integration_id,
            capture.sender,
            capture.to,
            []
        )
        expect(result).toBe('ineligible')
        expect(teamManager.getTeam).not.toHaveBeenCalled()
        expect(mockInternalFetch).not.toHaveBeenCalled()
    })

    it('bounds a stalled eligibility lookup before SES is called', async () => {
        mockFlag.mockImplementation(() => new Promise(() => {}))
        const lookup = service.checkEligibility(
            1,
            capture.source_id,
            capture.email_integration_id,
            capture.sender,
            capture.to,
            []
        )
        await jest.advanceTimersByTimeAsync(5000)
        expect(await lookup).toBe('retry')
    })

    it('checks eligibility without sending email content or BCC to the lookup API', async () => {
        mockFlag.mockResolvedValue(true)
        mockInternalFetch.mockResolvedValue({ status: 200, json: () => Promise.resolve({ eligible: true }) } as any)
        expect(
            await service.checkEligibility(
                1,
                capture.source_id,
                capture.email_integration_id,
                capture.sender,
                capture.to,
                []
            )
        ).toBe('eligible')
        const request = mockInternalFetch.mock.calls[0][1]
        const payload = parseJSON(request!.body as string)
        expect(Object.keys(payload).sort()).toEqual(['cc', 'email_integration_id', 'sender', 'source_id', 'to'])
    })

    it('emits an internal timeout event without email content', async () => {
        await service.recordSkipped(1, 'invocation-example', 'eligibility_timeout')
        expect(captureTeamEvent).toHaveBeenCalledWith(
            expect.objectContaining({ id: 1 }),
            'workflow_conversation_capture_skipped',
            { reason: 'eligibility_timeout', invocation_id: 'invocation-example' }
        )
    })

    it('records an unmatched send without retrying SES when the account changed after eligibility', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 200,
            json: () => Promise.resolve({ status: 'skipped_unmatched' }),
        } as any)
        const invocation: CyclotronJobInvocation = {
            id: 'capture-job-example',
            teamId: 1,
            functionId: 'workflow-example',
            state: null,
            queue: 'email',
            queuePriority: 0,
            queueParameters: { type: 'emailCapture', capture, attempts: 0 },
        }
        const result = await service.executeCapture(invocation)
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
            const invocation: CyclotronJobInvocation = {
                id: 'capture-job-example',
                teamId: 1,
                functionId: 'workflow-example',
                state: null,
                queue: 'email',
                queuePriority: 0,
                queueParameters: { type: 'emailCapture', capture, attempts },
            }
            const result = await service.executeCapture(invocation)
            expect(result.finished).toBe(false)
            expect(result.invocation.queueParameters).toEqual({ type: 'emailCapture', capture, attempts: attempts + 1 })
            expect(result.invocation.queueScheduledAt?.toMillis()).toBe(Date.now() + delay)
            expect(result.skipMonitoring).toBe(true)
        }
    )
})
