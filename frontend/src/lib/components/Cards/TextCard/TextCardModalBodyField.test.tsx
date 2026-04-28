import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'

jest.mock('lib/lemon-ui/LemonTextArea/LemonTextAreaMarkdown', () => ({
    LemonTextAreaMarkdown: (): JSX.Element => <div data-attr="text-card-edit-area">legacy</div>,
}))

jest.mock('lib/components/Cards/TextCard/TextCardMarkdownEditor', () => ({
    TextCardMarkdownEditor: (): JSX.Element => <div data-attr="text-card-rich-editor">rich</div>,
}))

import { TextCardModalBodyField } from './TextCardModalBodyField'

describe('TextCardModalBodyField', () => {
    it('renders the legacy editor after its chunk resolves', async () => {
        render(<TextCardModalBodyField shouldUseLegacyMarkdownEditor value="" onChange={jest.fn()} />)

        await waitFor(() => {
            expect(screen.getByText('legacy')).toHaveAttribute('data-attr', 'text-card-edit-area')
        })
    })

    it('renders the rich editor after its chunk resolves when not legacy', async () => {
        render(<TextCardModalBodyField shouldUseLegacyMarkdownEditor={false} value="" onChange={jest.fn()} />)

        await waitFor(() => {
            expect(screen.getByText('rich')).toHaveAttribute('data-attr', 'text-card-rich-editor')
        })
    })
})
