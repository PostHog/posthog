import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'

import type { ChatMessage } from '../../types'
import { Message } from './Message'

jest.mock('../Editor', () => ({
    SupportMarkdown: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    SupportRichContentPreview: () => null,
}))
jest.mock('../Editor/richContentToHtml', () => ({ richContentToHtml: () => null }))

describe('Message', () => {
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
})
