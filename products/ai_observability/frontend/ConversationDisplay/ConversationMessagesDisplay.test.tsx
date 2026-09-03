import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { CompatMessage, MultiModalContentItem } from '../types'
import {
    ConversationDisplayOption,
    ConversationMessagesDisplay,
    ImageMessageDisplay,
    LLMMessageDisplay,
} from './ConversationMessagesDisplay'
import { messageActionsMenuLogic } from './messageActionsMenuLogic'

// react-json-view is loaded via React.lazy, so the first render suspends on a code-split chunk.
// Under CI contention that resolve can exceed waitFor's 1s default, so give it headroom.
const JSON_VIEWER_TIMEOUT_MS = 5000

describe('LLMMessageDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        [
            'bracket-prefixed thinking text',
            '[Thinking: The user wants to build a todo app.]I will build a clean todo app for you!',
        ],
        [
            'bracket-prefixed tool call text',
            '[Tool Call: lov-write, Input: {"file_path":"src/pages/Index.tsx","content":"import React"}]',
        ],
        [
            'mixed thinking and tool call text',
            '[Thinking: Let me help.]Here is the answer.[Tool Call: write, Input: {"path":"index.ts"}]',
        ],
    ])('renders %s as plain text instead of empty JSON', (_label, content) => {
        const message: CompatMessage = { role: 'assistant', content }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show minimal />
            </Provider>
        )
        expect(container.textContent).toContain(content)
    })

    it.each([
        ['valid JSON object', '{"key": "value"}', 'key'],
        ['valid JSON array', '[{"role": "assistant", "content": "hello"}]', 'role'],
        ['truncated JSON object', '{"key": "val', 'key'],
    ])('renders %s as JSON', (_label, content, expectedSubstring) => {
        const message: CompatMessage = { role: 'assistant', content }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show minimal />
            </Provider>
        )
        expect(container.textContent).toContain(expectedSubstring)
    })

    it.each([
        ['valid JSON object', '{"key": "value"}', 'key'],
        ['valid JSON array', '[{"role": "assistant", "content": "hello"}]', 'role'],
        ['truncated JSON object', '{"key": "val', 'key'],
    ])('renders %s as JSON in expanded mode', async (_label, content, expectedSubstring) => {
        const message: CompatMessage = { role: 'assistant', content }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        await waitFor(
            () => {
                expect(container.querySelector('.react-json-view')).toBeInTheDocument()
            },
            { timeout: JSON_VIEWER_TIMEOUT_MS }
        )
        expect(container.textContent).toContain(expectedSubstring)
    })

    it.each(['{}', '[]'])('keeps empty JSON container %s as plain text in expanded mode', (content) => {
        const message: CompatMessage = { role: 'assistant', content }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('.react-json-view')).not.toBeInTheDocument()
        expect(container.textContent).toContain(content)
    })

    it('renders output_text JSON as plain text', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: JSON.stringify({ type: 'output_text', text: 'plain output text' }),
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.textContent).toContain('plain output text')
        expect(container.textContent).not.toContain('output_text')
    })

    it.each([
        [
            'image content object',
            { type: 'image', content: { type: 'image', image: 'https://example.com/image.png' } },
            'https://example.com/image.png',
        ],
        [
            'input_image object',
            { type: 'input_image', image_url: 'https://example.com/input-image.png' },
            'https://example.com/input-image.png',
        ],
    ])('renders %s JSON as an image', (_label, content, expectedSrc) => {
        const message: CompatMessage = {
            role: 'assistant',
            content: JSON.stringify(content),
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('img')?.getAttribute('src')).toBe(expectedSrc)
    })

    it('replaces a redacted sentinel reaching the JSON-string image path with a placeholder', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: JSON.stringify({ type: 'image', content: { type: 'image', image: '[base64 image redacted]' } }),
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('img')).toBeNull()
        expect(container.querySelector('[data-attr="ai-message-redacted-media"]')).not.toBeNull()
    })

    it('keeps the transcript when redacted audio replaces the player', () => {
        const message: CompatMessage = {
            role: 'user',
            content: [
                {
                    type: 'audio',
                    data: '[base64 audio redacted]',
                    transcript: 'a spoken sentence',
                    id: 'aud_1',
                    expires_at: 0,
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('audio')).toBeNull()
        expect(container.querySelector('[data-attr="ai-message-redacted-media"]')).not.toBeNull()
        expect(screen.getByText('a spoken sentence')).toBeInTheDocument()
    })

    it('keeps the filename when a redacted file replaces the download link', () => {
        const message: CompatMessage = {
            role: 'user',
            content: [{ type: 'file', file: { file_data: '[base64 file redacted]', filename: 'doc.pdf' } }],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('[data-attr="ai-message-redacted-media"]')).not.toBeNull()
        expect(screen.getByText('doc.pdf')).toBeInTheDocument()
    })

    it('renders OpenAI Responses input_text/input_image content parts as text and an image', () => {
        const dataUri = 'data:image/jpeg;base64,/9j/4AAQSkZ'
        const message: CompatMessage = {
            role: 'user',
            content: [
                { type: 'input_text', text: 'what is in this photo?' },
                { type: 'input_image', image_url: dataUri },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.textContent).toContain('what is in this photo?')
        expect(container.textContent).not.toContain('input_image')
        expect(container.textContent).not.toContain('base64')
        expect(container.querySelector('img')?.getAttribute('src')).toBe(dataUri)
    })

    it('renders an OpenAI Responses output_text content part as plain text', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [{ type: 'output_text', text: 'it is a photo of a cat' }],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.textContent).toContain('it is a photo of a cat')
        expect(container.textContent).not.toContain('output_text')
    })

    it('renders content[].type=function with object arguments as a tool-call block', async () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    id: 'call_abc',
                    function: {
                        name: 'get_weather',
                        arguments: { location: 'San Francisco' },
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('get_weather')
        expect(container.textContent).toContain('call_abc')
        await waitFor(() => {
            expect(container.textContent).toContain('location')
            expect(container.textContent).toContain('San Francisco')
        })
    })

    it('renders content[].type=function with stringified JSON arguments', async () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'get_weather',
                        arguments: '{"location": "Berlin"}',
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('get_weather')
        await waitFor(() => {
            expect(container.textContent).toContain('location')
            expect(container.textContent).toContain('Berlin')
        })
    })

    it('renders content[].type=function with unparseable string arguments without crashing', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'broken_call',
                        arguments: '{not valid json',
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('broken_call')
        expect(container.textContent).toContain('{not valid json')
    })

    it('renders content[].type=function without an id', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'no_id_call',
                        arguments: { foo: 'bar' },
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('no_id_call')
    })

    it('renders content[].type=function with arguments: null without crashing (header only)', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    id: 'call_xyz',
                    function: {
                        name: 'no_args_tool',
                        arguments: null,
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('no_args_tool')
        expect(container.textContent).toContain('call_xyz')
        expect(container.querySelector('.react-json-view')).toBeNull()
    })

    it('renders empty-args function as header only (no JSON viewer body)', () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                {
                    type: 'function',
                    function: {
                        name: 'empty_args_tool',
                        arguments: {},
                    },
                },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        expect(container.textContent).toContain('empty_args_tool')
        expect(container.querySelector('.react-json-view')).toBeNull()
    })

    it('preserves order across mixed text and function items in a single assistant message', async () => {
        const message: CompatMessage = {
            role: 'assistant',
            content: [
                { type: 'text', text: 'Searching now.' },
                {
                    type: 'function',
                    id: 'fs_001',
                    function: { name: 'file_search', arguments: { query: 'refund policy' } },
                },
                {
                    type: 'function',
                    id: 'mcp_002',
                    function: { name: 'mcp.fetch', arguments: '{"url":"https://example.com"}' },
                },
                { type: 'text', text: 'Done.' },
            ],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )
        await waitFor(() => {
            const text = container.textContent ?? ''
            expect(text).toContain('Searching now.')
            expect(text).toContain('file_search')
            expect(text).toContain('mcp.fetch')
            expect(text).toContain('Done.')
            // Ordering: text -> file_search -> mcp.fetch -> text
            const iSearching = text.indexOf('Searching now.')
            const iFileSearch = text.indexOf('file_search')
            const iMcpFetch = text.indexOf('mcp.fetch')
            const iDone = text.indexOf('Done.')
            expect(iSearching).toBeLessThan(iFileSearch)
            expect(iFileSearch).toBeLessThan(iMcpFetch)
            expect(iMcpFetch).toBeLessThan(iDone)
        })
    })
})

describe('ConversationMessagesDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const inputNormalized: CompatMessage[] = [
        { role: 'system', content: 'system input content' },
        { role: 'user', content: 'first user input content' },
        { role: 'assistant', content: 'assistant input content' },
        { role: 'user', content: 'second user input content' },
    ]
    const outputNormalized: CompatMessage[] = [{ role: 'assistant', content: 'assistant output content' }]

    it.each<[string, string, string[], string[]]>([
        [
            'expand_all',
            'expand_all',
            [
                'system input content',
                'first user input content',
                'assistant input content',
                'second user input content',
                'assistant output content',
            ],
            [],
        ],
        [
            'expand_user_only',
            'expand_user_only',
            ['first user input content', 'second user input content'],
            ['system input content', 'assistant input content', 'assistant output content'],
        ],
        [
            'collapse_except_output_and_last_input',
            'collapse_except_output_and_last_input',
            ['second user input content', 'assistant output content'],
            ['system input content', 'first user input content', 'assistant input content'],
        ],
    ])('display option %s shows/hides correct messages', (_label, displayOption, visible, hidden) => {
        render(
            <Provider>
                <ConversationMessagesDisplay
                    inputNormalized={inputNormalized}
                    outputNormalized={outputNormalized}
                    errorData={null}
                    raisedError={false}
                    displayOption={displayOption as ConversationDisplayOption}
                />
            </Provider>
        )

        for (const text of visible) {
            expect(screen.getByText(text)).toBeInTheDocument()
        }
        for (const text of hidden) {
            expect(screen.queryByText(text)).not.toBeInTheDocument()
        }
    })

    it('mounts one message actions menu only after a trigger is used', async () => {
        const { container, rerender } = render(
            <Provider>
                <ConversationMessagesDisplay
                    inputNormalized={inputNormalized}
                    outputNormalized={outputNormalized}
                    errorData={null}
                    raisedError={false}
                />
            </Provider>
        )

        const triggers = container.querySelectorAll<HTMLButtonElement>('[data-attr="llma-message-actions-trigger"]')

        expect(triggers).toHaveLength(5)
        expect(container.querySelectorAll('[aria-haspopup="true"]')).toHaveLength(5)
        expect(container.querySelectorAll('[data-menu-mounted="true"]')).toHaveLength(0)

        triggers[0].focus()
        fireEvent.click(triggers[0])

        expect(container.querySelectorAll('[data-menu-mounted="true"]')).toHaveLength(1)
        expect(document.activeElement).toBe(container.querySelectorAll('[data-attr="llma-message-actions-trigger"]')[0])
        expect(await screen.findByText('Translate')).toBeInTheDocument()

        fireEvent.click(container.querySelectorAll('[data-attr="llma-message-actions-trigger"]')[1])

        expect(container.querySelectorAll('[aria-haspopup="true"]')).toHaveLength(5)
        expect(container.querySelectorAll('[data-menu-mounted="true"]')).toHaveLength(1)
        expect(document.activeElement).toBe(container.querySelectorAll('[data-attr="llma-message-actions-trigger"]')[1])

        rerender(
            <Provider>
                <ConversationMessagesDisplay
                    inputNormalized={[...inputNormalized, { role: 'user', content: 'extra user input' }]}
                    outputNormalized={outputNormalized}
                    errorData={null}
                    raisedError={false}
                />
            </Provider>
        )

        // A different conversation must clear the active menu key, or its matching
        // message would mount with the menu already open and steal focus.
        expect(container.querySelectorAll('[aria-haspopup="true"]')).toHaveLength(6)
        expect(container.querySelectorAll('[data-menu-mounted="true"]')).toHaveLength(0)
    })

    it('keeps a translation when the shared menu moves to another message and back', () => {
        const { container } = render(
            <Provider>
                <ConversationMessagesDisplay
                    inputNormalized={inputNormalized}
                    outputNormalized={outputNormalized}
                    errorData={null}
                    raisedError={false}
                />
            </Provider>
        )
        const getTriggers = (): NodeListOf<HTMLButtonElement> =>
            container.querySelectorAll<HTMLButtonElement>('[data-attr="llma-message-actions-trigger"]')
        const translation = { translation: 'contenido de entrada del sistema', targetLanguage: 'es' as const }

        fireEvent.click(getTriggers()[0])
        messageActionsMenuLogic.findMounted({ content: 'system input content' })?.actions.translateSuccess(translation)

        fireEvent.click(getTriggers()[1])
        fireEvent.click(getTriggers()[0])

        expect(messageActionsMenuLogic.findMounted({ content: 'system input content' })?.values.translation).toEqual(
            translation
        )
    })

    it.each<[string, unknown, unknown, unknown, unknown, string | null]>([
        [
            'only output tokens were billed',
            2048,
            undefined,
            undefined,
            undefined,
            'The provider reported 2,048 output tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        [
            'only reasoning tokens were billed',
            undefined,
            442,
            undefined,
            undefined,
            'The provider reported 442 reasoning tokens but no content was captured. The model may have spent its budget on reasoning.',
        ],
        [
            'reasoning matches the billed output exactly',
            442,
            442,
            undefined,
            undefined,
            'The provider reported 442 output tokens but no content was captured. All of them may have been reasoning.',
        ],
        [
            'reasoning exceeds the output count, so the output is missing content',
            400,
            500,
            undefined,
            undefined,
            'The provider reported 400 output tokens and 500 reasoning tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        [
            'a provider reported the count as a string',
            '512',
            undefined,
            undefined,
            undefined,
            'The provider reported 512 output tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        [
            'a provider spelled the token limit in upper case',
            2048,
            undefined,
            undefined,
            'MAX_TOKENS',
            'The provider reported 2,048 output tokens but no content was captured. The response hit its token limit.',
        ],
        [
            'the stop reason outranks the reasoning-token guess',
            undefined,
            442,
            undefined,
            'length',
            'The provider reported 442 reasoning tokens but no content was captured. The response hit its token limit.',
        ],
        [
            'the provider blocked the response without billing anything',
            0,
            0,
            undefined,
            'PROHIBITED_CONTENT',
            'The provider blocked the response.',
        ],
        [
            'the stop reason describes a normal ending',
            2048,
            undefined,
            undefined,
            'end_turn',
            'The provider reported 2,048 output tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        [
            'reasoning is only a fraction of the billed output',
            2048,
            12,
            undefined,
            undefined,
            'The provider reported 2,048 output tokens and 12 reasoning tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        [
            'the text-token split says none of the output was text',
            169,
            56,
            0,
            undefined,
            'The provider reported 169 output tokens and 56 reasoning tokens but no content was captured. None of them were text.',
        ],
        [
            'the text-token split says text was billed too',
            442,
            442,
            113,
            undefined,
            'The provider reported 442 output tokens and 442 reasoning tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        [
            'a provider hyphenated the stop reason',
            2048,
            undefined,
            undefined,
            'content-filter',
            'The provider reported 2,048 output tokens but no content was captured. The provider blocked the response.',
        ],
        [
            'an older SDK sent the count as an object',
            { total: 10585, noCache: 10585, cacheRead: 0 },
            undefined,
            undefined,
            undefined,
            'The provider reported 10,585 output tokens but no content was captured. The response may have been cut short, or the SDK may not have captured it.',
        ],
        ['the provider billed nothing', 0, 0, undefined, undefined, null],
        ['no token counts arrived', undefined, undefined, undefined, undefined, null],
    ])(
        'empty output explains the gap when %s',
        (_label, outputTokens, reasoningTokens, textOutputTokens, stopReason, expected) => {
            const { container } = render(
                <Provider>
                    <ConversationMessagesDisplay
                        inputNormalized={inputNormalized}
                        outputNormalized={[]}
                        errorData={null}
                        raisedError={false}
                        outputTokens={outputTokens}
                        reasoningTokens={reasoningTokens}
                        textOutputTokens={textOutputTokens}
                        stopReason={stopReason}
                    />
                </Provider>
            )

            expect(screen.getByText('No output')).toBeInTheDocument()
            const explanation = container.querySelector('[data-attr="ai-empty-output-explanation"]')
            if (expected !== null) {
                expect(explanation).toHaveTextContent(expected)
                // The notice names a cause and the link carries the fix. A typo'd anchor dead-ends there.
                expect(explanation!.querySelector('a')).toHaveAttribute(
                    'href',
                    'https://posthog.com/docs/ai-observability/troubleshooting#why-does-my-generation-show-no-output'
                )
            } else {
                expect(explanation).toBeNull()
            }
        }
    )
})

describe('ImageMessageDisplay', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('tags rendered images with a stable data-attr for e2e targeting', () => {
        const { container } = render(
            <ImageMessageDisplay message={{ content: { image: 'data:image/png;base64,iVBORw0KGgo=' } }} />
        )

        const image = container.querySelector('img')
        expect(image).not.toBeNull()
        expect(image).toHaveAttribute('data-attr', 'ai-message-image')
    })

    it('tags the OpenAI image_url content branch with the same data-attr', () => {
        const message: CompatMessage = {
            role: 'user',
            content: [{ type: 'image_url', image_url: { url: 'data:image/png;base64,iVBORw0KGgo=' } }],
        }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        const image = container.querySelector('img')
        expect(image).not.toBeNull()
        expect(image).toHaveAttribute('data-attr', 'ai-message-image')
    })

    const REDACTED = '[base64 image redacted]'
    const redactedParts: [string, MultiModalContentItem, string][] = [
        ['python image sentinel', { type: 'image_url', image_url: { url: REDACTED } }, 'Image'],
        ['node image sentinel', { type: 'image_url', image_url: { url: '[base64 image/png redacted]' } }, 'Image'],
        ['data-uri-wrapped sentinel', { type: 'image_url', image_url: { url: `data:;base64,${REDACTED}` } }, 'Image'],
        ['vercel image sentinel', { type: 'image', image: REDACTED }, 'Image'],
        ['input_image sentinel', { type: 'input_image', image_url: REDACTED }, 'Image'],
        [
            'anthropic image sentinel',
            { type: 'image', source: { type: 'base64', media_type: 'image/png', data: REDACTED } },
            'Image',
        ],
        [
            'gemini snake_case image sentinel',
            { type: 'image', inline_data: { mime_type: 'image/png', data: REDACTED } },
            'Image',
        ],
        [
            'gemini camelCase image sentinel',
            { type: 'image', inlineData: { mimeType: 'image/png', data: REDACTED } },
            'Image',
        ],
        ['file sentinel', { type: 'file', file: { file_data: '[base64 file redacted]', filename: 'doc.pdf' } }, 'File'],
        [
            'anthropic document sentinel',
            { type: 'document', source: { type: 'base64', media_type: 'application/pdf', data: REDACTED } },
            'File',
        ],
        [
            'gemini document sentinel',
            { type: 'document', inline_data: { mime_type: 'application/pdf', data: REDACTED } },
            'File',
        ],
        [
            'audio sentinel',
            { type: 'audio', data: '[base64 audio redacted]', transcript: '', id: 'aud_1', expires_at: 0 },
            'Audio',
        ],
    ]

    it.each(redactedParts)('replaces %s with a placeholder instead of a broken media element', (_name, part, label) => {
        const message: CompatMessage = { role: 'user', content: [part] }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('img')).toBeNull()
        expect(container.querySelector('[data-attr="ai-message-redacted-media"]')).not.toBeNull()
        expect(screen.getByText(`${label} not captured.`)).toBeInTheDocument()
        expect(screen.getByRole('link')).toHaveAttribute(
            'href',
            'https://posthog.com/docs/ai-observability/large-events'
        )
    })

    it.each([
        ['inline data uri', 'data:image/png;base64,iVBORw0KGgo='],
        ['offloaded blob pointer', `phaiblob://v1/sha256/${'a'.repeat(64)}?mime=image%2Fpng&size=131072`],
        ['plain remote https url', 'https://example.com/a.png'],
    ])('keeps rendering an image for %s', (_name, url) => {
        const message: CompatMessage = { role: 'user', content: [{ type: 'image_url', image_url: { url } }] }
        const { container } = render(
            <Provider>
                <LLMMessageDisplay message={message} show />
            </Provider>
        )

        expect(container.querySelector('img')).not.toBeNull()
        expect(container.querySelector('[data-attr="ai-message-redacted-media"]')).toBeNull()
    })
})
