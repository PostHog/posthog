import { fireEvent, render } from '@testing-library/react'

import { MarkdownNotebook } from './MarkdownNotebook'

const SECTIONED_MARKDOWN = [
    '# Notebook title',
    '<Section title="Setup" />',
    'Inside the section',
    '<SectionEnd />',
    'Outside the section',
].join('\n\n')

describe('NotebookSection', () => {
    it('hides the blocks of a collapsed section and persists the collapsed state into the markdown', () => {
        const onChange = jest.fn()
        const { container } = render(<MarkdownNotebook value={SECTIONED_MARKDOWN} onChange={onChange} />)
        const toggle = container.querySelector('[data-attr="markdown-notebook-section-toggle"]') as HTMLButtonElement

        expect(container.textContent).toContain('Inside the section')

        fireEvent.click(toggle)

        expect(container.textContent).not.toContain('Inside the section')
        expect(container.textContent).toContain('Outside the section')
        expect(onChange).toHaveBeenLastCalledWith(
            SECTIONED_MARKDOWN.replace('<Section title="Setup" />', '<Section title="Setup" collapsed />')
        )

        fireEvent.click(toggle)

        expect(container.textContent).toContain('Inside the section')
        expect(onChange).toHaveBeenLastCalledWith(SECTIONED_MARKDOWN)
    })

    it('renames a section through the title field', () => {
        const onChange = jest.fn()
        const { container } = render(<MarkdownNotebook value={SECTIONED_MARKDOWN} onChange={onChange} />)
        const titleInput = container.querySelector('[aria-label="Section title"]') as HTMLInputElement

        fireEvent.change(titleInput, { target: { value: 'Data prep' } })
        fireEvent.blur(titleInput)

        expect(onChange).toHaveBeenLastCalledWith(SECTIONED_MARKDOWN.replace('title="Setup"', 'title="Data prep"'))
    })

    it('keeps the blocks of a section that gets ungrouped', () => {
        const onChange = jest.fn()
        const { container } = render(<MarkdownNotebook value={SECTIONED_MARKDOWN} onChange={onChange} />)

        fireEvent.click(container.querySelector('[data-attr="markdown-notebook-section-remove"]') as HTMLButtonElement)

        expect(onChange).toHaveBeenLastCalledWith(
            ['# Notebook title', 'Inside the section', 'Outside the section'].join('\n\n')
        )
    })
})
