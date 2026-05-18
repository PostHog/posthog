import { getAsyncFunctionHandler } from '../async-function-registry'
import './llm-gateway'
import { __TESTING_ALLOWED_LLM_TEMPLATE_IDS } from './llm-gateway'

// Defense-in-depth: postHogLLMChatCompletion injects PostHog's internal service LLM gateway key
// into outbound requests, so it MUST NOT be callable from arbitrary user-authored destination
// Hog functions. The template_id gate is the load-bearing check — these tests assert it actually
// rejects unauthorized callers and accepts the built-in LLM templates. Without this test the
// rest of the template-level tests pass even if the gate is silently disabled, because they
// always run inside an allowed template.
describe('llm-gateway template_id gate', () => {
    const buildContext = (templateId: string | undefined): any => ({
        invocation: {
            hogFunction: { template_id: templateId },
        },
        globals: { event: { distinct_id: 'u1' } },
        llmGatewayUrl: 'http://gw.test',
        llmGatewayApiKey: 'svc',
    })

    const buildResult = (): any => ({
        invocation: { queueParameters: undefined },
    })

    const buildOpts = () => ({
        model: 'gpt-5.4-nano',
        messages: [{ role: 'user', content: 'hi' }],
    })

    it('rejects a caller whose template_id is not on the allowlist', () => {
        const handler = getAsyncFunctionHandler('postHogLLMChatCompletion')
        expect(handler).toBeDefined()
        expect(() =>
            handler!.execute([buildOpts()], buildContext('template-some-user-destination'), buildResult())
        ).toThrow(/restricted to PostHog-built LLM templates/)
    })

    it('rejects a caller with an empty/undefined template_id', () => {
        const handler = getAsyncFunctionHandler('postHogLLMChatCompletion')
        expect(() => handler!.execute([buildOpts()], buildContext(undefined), buildResult())).toThrow(
            /restricted to PostHog-built LLM templates/
        )
    })

    it.each([
        'template-posthog-llm-classify',
        'template-posthog-llm-summarize',
        'template-posthog-llm-extract',
    ] as const)('accepts the %s template', (templateId) => {
        const handler = getAsyncFunctionHandler('postHogLLMChatCompletion')
        const result = buildResult()
        expect(() => handler!.execute([buildOpts()], buildContext(templateId), result)).not.toThrow()
        // Sanity: the fetch was actually queued (not just silently no-op'd).
        expect(result.invocation.queueParameters).toBeDefined()
    })

    it('exposes the allowlist with the expected templates', () => {
        // Anyone changing this set needs to update the gate intentionally — keeping a snapshot
        // here makes a silent expansion show up in code review.
        expect([...__TESTING_ALLOWED_LLM_TEMPLATE_IDS].sort()).toEqual([
            'template-posthog-llm-classify',
            'template-posthog-llm-extract',
            'template-posthog-llm-summarize',
        ])
    })
})
