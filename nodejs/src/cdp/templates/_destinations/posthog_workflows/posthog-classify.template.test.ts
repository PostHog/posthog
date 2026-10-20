import { TemplateTester } from '../../test/test-helpers'
import { template } from './posthog-classify.template'

describe('posthog classify template', () => {
    const tester = new TemplateTester(template)

    const inputs = {
        question: 'Is this ticket spam?',
        context: { subject: 'Buy SEO' },
        categories: { spam: 'Cold outreach', support: 'A customer asking for help' },
    }
    const answer = { category: 'spam', confidence: 0.9, probabilities: { spam: 0.9, support: 0.1 } }

    const mockAnswer = (status: number, body: unknown): void => {
        tester.mockInternalFetch.mockResolvedValueOnce({
            status,
            text: () => Promise.resolve(JSON.stringify(body)),
        })
    }

    beforeEach(async () => {
        await tester.beforeEach()
    })

    it('asks again after the scheduled wait when the model was busy', async () => {
        mockAnswer(503, { detail: 'The model is busy or unreachable. Retry later.' })
        mockAnswer(200, answer)

        const busy = await tester.invoke(inputs, undefined, { hogFlow: { id: 'flow-1' } })
        expect(busy.finished).toBe(false)
        expect(busy.invocation.queueScheduledAt).toBeDefined()

        const asked = await tester.resumeInvocation(busy.invocation)
        expect(tester.mockInternalFetch).toHaveBeenCalledTimes(2)

        const done = await tester.resumeInvocation(asked.invocation)
        expect(done.error).toBeUndefined()
        expect(done).toMatchObject({ finished: true, execResult: answer })
    })
})
