import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { ChatMessage } from '../../types'
import { Message } from './Message'

jest.mock('../Editor', () => ({
    SupportMarkdown: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    SupportRichContentPreview: () => null,
}))
jest.mock('../Editor/richContentToHtml', () => ({ richContentToHtml: () => null }))

describe('Message', () => {
    afterEach(cleanup)

    it('loads the preserved full email body when one is available', () => {
        const onViewFullEmail = jest.fn()
        const message: ChatMessage = {
            id: 'message-id',
            content: 'Visible reply',
            authorType: 'customer',
            authorName: 'Customer',
            createdAt: '2026-01-01T00:00:00Z',
            hasFullEmailContent: true,
        }

        render(<Message message={message} isCustomer onViewFullEmail={onViewFullEmail} />)

        fireEvent.click(screen.getByText('View full email'))
        expect(onViewFullEmail).toHaveBeenCalledTimes(1)
    })

    it('prefills a private AI draft with Use as reply', () => {
        const onApplyAiDraft = jest.fn()
        const message: ChatMessage = {
            id: 'ai-draft',
            content: 'Add the snippet to every page.',
            authorType: 'AI',
            authorName: 'PostHog Assistant',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
            persistAs: 'reply',
            confidence: 0.64,
            citations: ['https://example.com/docs/sdk'],
        }

        render(<Message message={message} isCustomer={false} onApplyAiDraft={onApplyAiDraft} />)

        fireEvent.click(screen.getByText('Use as reply'))
        expect(onApplyAiDraft).toHaveBeenCalledTimes(1)
        expect(screen.getByText('64% confidence')).toBeInTheDocument()
        expect(screen.getByText('example.com/docs/sdk')).toBeInTheDocument()
    })

    it('offers Use question on a private clarifying draft', () => {
        const message: ChatMessage = {
            id: 'ai-question',
            content: 'Suggested question for the customer:\n- Which SDK?',
            authorType: 'AI',
            authorName: 'PostHog Assistant',
            createdAt: '2026-01-01T00:00:00Z',
            isPrivate: true,
            persistAs: 'clarification',
            clarifyingQuestions: ['Which SDK are you using?'],
        }

        render(<Message message={message} isCustomer={false} onApplyAiDraft={jest.fn()} />)

        expect(screen.getByText('Use question')).toBeInTheDocument()
        expect(screen.queryByText('Use as reply')).not.toBeInTheDocument()
    })
})
