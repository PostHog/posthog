import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-email.template'

describe('posthog email template', () => {
    const tester = new TemplateTester(template)
    const inputs = {
        subject: 'Sync failed',
        body: 'The sync for the table "orders" failed.',
        action_url: 'https://us.posthog.com/project/1/data-warehouse',
    }

    beforeEach(async () => {
        await tester.beforeEach()
        tester.mockSystemEmailService.sendFromInvocation.mockReset()
    })

    it('sends the content inline and leaves the invocation off the email queue', async () => {
        tester.mockSystemEmailService.sendFromInvocation.mockResolvedValue({ success: true })

        const paused = await tester.invoke(inputs)

        expect(paused.invocation.queueParameters).toBeUndefined()
        expect(paused.invocation.queue).toEqual('hog')
        const response = await tester.resumeInvocation(paused.invocation)
        expect(response.error).toBeUndefined()
        expect(response.finished).toEqual(true)
        expect(tester.mockSystemEmailService.sendFromInvocation).toHaveBeenCalledTimes(1)
        expect(tester.mockSystemEmailService.sendFromInvocation.mock.calls[0][0]).toEqual({
            ...inputs,
            action_label: 'Open in PostHog',
        })
    })

    it.each([
        ['the service reports a failure', () => Promise.resolve({ success: false, error: 'No project members' })],
        ['the service throws', () => Promise.reject(new Error('connection reset'))],
    ])('fails the invocation when %s', async (_name, outcome) => {
        tester.mockSystemEmailService.sendFromInvocation.mockImplementation(outcome)

        const paused = await tester.invoke(inputs)
        const response = await tester.resumeInvocation(paused.invocation)

        expect(response.finished).toEqual(true)
        expect(String(response.error)).toContain('Email failed to send')
        expect(paused.invocation.queueParameters).toBeUndefined()
    })
})
