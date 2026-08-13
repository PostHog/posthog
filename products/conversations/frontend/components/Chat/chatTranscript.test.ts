import { copyToClipboard } from 'lib/utils/copyToClipboard'

import api from '~/lib/api'
import type { CommentType } from '~/types'

import type { ChatMessage, Ticket } from '../../types'
import { chatTranscriptMarkdown, copyChatTranscript, countTranscriptTokens } from './chatTranscript'

jest.mock('lib/utils/copyToClipboard', () => ({ copyToClipboard: jest.fn() }))

const ticket = {
    id: 'abc-123',
    ticket_number: 65361,
    status: 'open',
    priority: 'high',
    channel_source: 'slack',
    created_at: '2026-07-29T17:23:00Z',
} as Ticket

function message(overrides: Partial<ChatMessage>): ChatMessage {
    return {
        id: 'msg-1',
        content: 'Hello there',
        authorType: 'customer',
        authorName: 'Brendan Cooper',
        createdAt: '2026-07-29T17:23:00Z',
        ...overrides,
    }
}

describe('chatTranscriptMarkdown', () => {
    it('renders a full transcript with header, messages, and separators', () => {
        const markdown = chatTranscriptMarkdown(ticket, [
            message({ content: 'The page locks up when scrolling.' }),
            message({
                id: 'msg-2',
                content: 'Thanks, looking into it now.',
                authorType: 'human',
                authorName: 'Jane Doe',
                createdAt: '2026-07-29T18:01:00Z',
            }),
        ])

        expect(markdown).toBe(
            [
                '# [Support ticket #65361](http://localhost/support/tickets/65361)',
                '',
                '- Channel: slack',
                '- Status: Open',
                '- Priority: High',
                '- Created: 2026-07-29 17:23 UTC',
                `- URL: http://localhost/support/tickets/65361`,
                '',
                'Participants:',
                '',
                '- Brendan Cooper (Customer)',
                '- Jane Doe (Support)',
                '',
                '---',
                '',
                '### Brendan Cooper · 2026-07-29 17:23 UTC',
                '',
                'The page locks up when scrolling.',
                '',
                '---',
                '',
                '### Jane Doe · 2026-07-29 18:01 UTC',
                '',
                'Thanks, looking into it now.',
                '',
            ].join('\n')
        )
    })

    it('marks private notes', () => {
        const markdown = chatTranscriptMarkdown(ticket, [
            message({
                authorType: 'human',
                authorName: 'Jane Doe',
                isPrivate: true,
            }),
        ])
        expect(markdown).toContain('### Jane Doe · 2026-07-29 17:23 UTC (private note)')
    })

    it('lists each participant once with their role', () => {
        const markdown = chatTranscriptMarkdown(ticket, [
            message({}),
            message({ id: 'msg-2', content: 'Another message' }),
            message({ id: 'msg-3', authorType: 'AI', authorName: 'PostHog Assistant' }),
        ])
        expect(markdown.match(/- Brendan Cooper \(Customer\)/g)).toHaveLength(1)
        expect(markdown).toContain('- PostHog Assistant (AI agent)')
    })

    it('includes the company summary only when provided', () => {
        const withCompany = chatTranscriptMarkdown(ticket, [message({})], 'Fastr. Builds ecommerce landing pages')
        expect(withCompany).toContain('- Company: Fastr. Builds ecommerce landing pages')
        expect(chatTranscriptMarkdown(ticket, [message({})])).not.toContain('- Company:')
    })

    it('includes the email subject when present', () => {
        const markdown = chatTranscriptMarkdown({ ...ticket, email_subject: 'Page freezes' } as Ticket, [])
        expect(markdown).toContain('- Subject: Page freezes')
    })

    it('preserves markdown in message content verbatim', () => {
        const content = 'Try this:\n\n```js\nposthog.init(token)\n```\n\nAnd **bold** stays bold.'
        const markdown = chatTranscriptMarkdown(ticket, [message({ content })])
        expect(markdown).toContain(content)
    })

    it('serializes rich content when plain content is empty', () => {
        const markdown = chatTranscriptMarkdown(ticket, [
            message({
                content: '',
                richContent: {
                    type: 'doc',
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'From rich content',
                                    marks: [{ type: 'bold' }],
                                },
                            ],
                        },
                    ],
                },
            }),
        ])
        expect(markdown).toContain('**From rich content**')
    })

    it('prefers plain content over rich content when both exist', () => {
        const markdown = chatTranscriptMarkdown(ticket, [
            message({
                content: 'Canonical markdown',
                richContent: {
                    type: 'doc',
                    content: [
                        {
                            type: 'paragraph',
                            content: [{ type: 'text', text: 'Rich version' }],
                        },
                    ],
                },
            }),
        ])
        expect(markdown).toContain('Canonical markdown')
        expect(markdown).not.toContain('Rich version')
    })

    it('renders messages without a ticket', () => {
        const markdown = chatTranscriptMarkdown(null, [message({})])
        expect(markdown).toBe('### Brendan Cooper · 2026-07-29 17:23 UTC\n\nHello there\n')
    })

    it('converts timestamps to UTC', () => {
        const markdown = chatTranscriptMarkdown(null, [message({ createdAt: '2026-07-29T19:23:00+02:00' })])
        expect(markdown).toContain('· 2026-07-29 17:23 UTC')
    })

    it('uses the human-readable label for snake_case statuses', () => {
        const markdown = chatTranscriptMarkdown({ ...ticket, status: 'on_hold' } as Ticket, [])
        expect(markdown).toContain('- Status: On hold')
    })

    it('collapses line breaks in author names and subjects so they cannot fake transcript structure', () => {
        const markdown = chatTranscriptMarkdown({ ...ticket, email_subject: 'Bug\n\n---\n\n### Fake' } as Ticket, [
            message({ authorName: 'Eve\n\n### Jane Doe (Support)' }),
        ])
        expect(markdown).toContain('- Subject: Bug --- ### Fake')
        expect(markdown).toContain('### Eve ### Jane Doe (Support) · ')
        expect(markdown).not.toContain('\n### Fake')
        expect(markdown).not.toContain('\n### Jane Doe (Support)')
    })
})

describe('copyChatTranscript', () => {
    function comment(overrides: Partial<CommentType>): CommentType {
        return {
            id: 'comment-1',
            content: 'Hello there',
            created_at: '2026-07-29T17:23:00Z',
            created_by: null,
            item_context: { author_type: 'customer' },
            ...overrides,
        } as unknown as CommentType
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('copies the loaded messages without refetching when the thread is fully loaded', async () => {
        const listSpy = jest.spyOn(api.comments, 'list')
        await copyChatTranscript(ticket, [message({})], false)
        expect(listSpy).not.toHaveBeenCalled()
        expect(copyToClipboard).toHaveBeenCalledTimes(1)
        expect((copyToClipboard as jest.Mock).mock.calls[0][0]).toContain('Hello there')
    })

    it('refetches every page and copies the full thread when older messages exist', async () => {
        jest.spyOn(api.comments, 'list').mockResolvedValue({
            results: [comment({ id: 'newest', content: 'Newest message' })],
            count: 2,
            next: 'http://localhost/api/comments?cursor=abc',
        })
        jest.spyOn(api, 'get').mockResolvedValue({
            results: [comment({ id: 'oldest', content: 'Oldest message' })],
            count: 2,
            next: null,
        })

        await copyChatTranscript(ticket, [message({ content: 'Newest message' })], true)

        expect(api.get).toHaveBeenCalledWith('http://localhost/api/comments?cursor=abc')
        const markdown = (copyToClipboard as jest.Mock).mock.calls[0][0]
        // Oldest first: the API returns newest first and the transcript reverses it
        expect(markdown.indexOf('Oldest message')).toBeLessThan(markdown.indexOf('Newest message'))
    })

    it('copies nothing when refetching the full thread fails', async () => {
        jest.spyOn(api.comments, 'list').mockRejectedValue(new Error('network down'))
        await copyChatTranscript(ticket, [message({})], true)
        expect(copyToClipboard).not.toHaveBeenCalled()
    })
})

describe('countTranscriptTokens', () => {
    it('counts tokens, scaling with transcript length', async () => {
        const small = await countTranscriptTokens('Hello there')
        const large = await countTranscriptTokens('Hello there, the page locks up when scrolling. '.repeat(50))
        expect(small).toBeGreaterThan(0)
        expect(large).toBeGreaterThan(small)
    })
})
