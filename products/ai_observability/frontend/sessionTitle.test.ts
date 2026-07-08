import { resolveTitleFromInputs } from './sessionTitle'

describe('resolveTitleFromInputs', () => {
    it('returns null when no payload yields a title', () => {
        expect(resolveTitleFromInputs(null, null)).toBeNull()
        expect(resolveTitleFromInputs(undefined, undefined)).toBeNull()
        expect(resolveTitleFromInputs({ messages: [] }, null)).toBeNull()
    })

    it('prefers the first user message in the input_state messages wrapper', () => {
        const inputState = {
            agent_mode: null,
            messages: [
                { role: 'system', content: 'You are a helpful assistant' },
                { role: 'user', content: 'Address Book analytic' },
            ],
        }
        expect(resolveTitleFromInputs(inputState, null)).toBe('Address Book analytic')
    })

    it('treats LangChain type:"human" messages as user messages', () => {
        const inputState = {
            messages: [
                { type: 'system', content: 'system prompt' },
                { type: 'human', content: 'Hello, I need an export of subscribed users.' },
            ],
        }
        expect(resolveTitleFromInputs(inputState, null)).toBe('Hello, I need an export of subscribed users.')
    })

    it('falls back to the generation input, skipping system messages', () => {
        const genInput = [
            { role: 'system', content: 'You are an expert in crisp conversation titles.' },
            { role: 'system', content: 'You are currently in project Default project.' },
            { role: 'user', content: 'I have connected PostHog Web Tracking and need a dashboard' },
        ]
        expect(resolveTitleFromInputs(null, genInput)).toBe(
            'I have connected PostHog Web Tracking and need a dashboard'
        )
    })

    it.each([
        { desc: 'a bare-string generation input', input: 'how do I add a feature flag?' },
        { desc: 'a role-less message object', input: [{ content: 'how do I add a feature flag?' }] },
    ])('treats role-less generation input as the user prompt: $desc', ({ input }) => {
        expect(resolveTitleFromInputs(null, input)).toBe('how do I add a feature flag?')
    })

    it('uses the trace name when no user message is present', () => {
        expect(resolveTitleFromInputs(null, null, 'switch-project')).toBe('switch-project')
    })

    it.each([['LangGraph'], ['RunnableSequence'], ['ChatPromptTemplate'], ['langgraph']])(
        'rejects generic trace name %p (returns null when no other signal)',
        (name) => {
            expect(resolveTitleFromInputs(null, null, name)).toBeNull()
        }
    )

    it('prefers a real user message over the trace name', () => {
        const inputState = { messages: [{ role: 'user', content: 'plan a trip to Japan' }] }
        expect(resolveTitleFromInputs(inputState, null, 'switch-project')).toBe('plan a trip to Japan')
    })

    it.each([['system_reminder'], ['voice_mode'], ['attached_context']])(
        'skips internal <%s> scaffold messages and uses the first real user message',
        (tag) => {
            const inputState = {
                messages: [
                    { role: 'user', content: `<${tag}>internal scaffold noise</${tag}>` },
                    { role: 'user', content: "What changed in last month's signup funnel?" },
                ],
            }
            expect(resolveTitleFromInputs(inputState, null)).toBe("What changed in last month's signup funnel?")
        }
    )

    it('skips a leading stack of internal scaffolds before the first human message', () => {
        const inputState = {
            messages: [
                { role: 'user', content: '<system_reminder>Your initial mode is product_analytics.</system_reminder>' },
                { role: 'user', content: '<voice_mode>The user is no longer in hands-free voice mode.</voice_mode>' },
                { role: 'user', content: '<attached_context>Dashboards</attached_context>' },
                { role: 'user', content: "What changed in last month's signup funnel?" },
            ],
        }
        expect(resolveTitleFromInputs(inputState, null)).toBe("What changed in last month's signup funnel?")
    })

    it.each([
        {
            desc: 'collapses whitespace',
            content: 'multi\nline\n\nmessage   with   spaces',
            expected: 'multi line message with spaces',
        },
        {
            desc: 'does not truncate short titles',
            content: 'short message',
            expected: 'short message',
        },
        {
            desc: 'extracts text from array-shaped content (Anthropic typed parts)',
            content: [
                { type: 'text', text: 'Look at this image' },
                { type: 'image', url: 'https://example.com/a.png' },
            ],
            expected: 'Look at this image',
        },
    ])('extracts title content: $desc', ({ content, expected }) => {
        expect(resolveTitleFromInputs({ messages: [{ role: 'user', content }] }, null)).toBe(expected)
    })

    it('skips messages with empty content and uses the next user message', () => {
        const inputState = {
            messages: [
                { role: 'user', content: '' },
                { role: 'user', content: 'actual question' },
            ],
        }
        expect(resolveTitleFromInputs(inputState, null)).toBe('actual question')
    })

    it.each([
        {
            desc: 'truncates a long title with an ellipsis at the default length',
            content:
                "We've just released SpicyCam - I want to know what the initial user engagement and intent is like - are the users enjoying the new feature?",
            maxLength: undefined,
            maxOut: 121, // 120 + ellipsis
        },
        {
            desc: 'accepts a custom maxLength',
            content: 'this is a moderately long sentence that should be cut',
            maxLength: 20,
            maxOut: 21,
        },
    ])('$desc', ({ content, maxLength, maxOut }) => {
        const inputState = { messages: [{ role: 'user', content }] }
        const result =
            maxLength === undefined
                ? resolveTitleFromInputs(inputState, null)
                : resolveTitleFromInputs(inputState, null, undefined, maxLength)
        expect(result).toBeTruthy()
        expect(result!.length).toBeLessThanOrEqual(maxOut)
        expect(result!.endsWith('…')).toBe(true)
    })

    it('backs off to a word boundary instead of cutting mid-word', () => {
        const content =
            "We've just released SpicyCam - I want to know what the initial user engagement and intent is like - are the users enjoying the new feature?"
        const result = resolveTitleFromInputs({ messages: [{ role: 'user', content }] }, null)
        expect(result).not.toContain('enjoyi…')
    })
})
