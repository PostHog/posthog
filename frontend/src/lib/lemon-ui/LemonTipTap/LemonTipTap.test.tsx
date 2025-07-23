import { render } from '@testing-library/react'
import { LemonTipTap } from './LemonTipTap'

describe('LemonTipTap', () => {
    it('renders basic markdown content', () => {
        const markdown = '# Hello World\n\nThis is **bold** text.'
        const { container } = render(<LemonTipTap>{markdown}</LemonTipTap>)

        expect(container.querySelector('.LemonTipTap')).toBeInTheDocument()
        expect(container.querySelector('.ProseMirror')).toBeInTheDocument()
    })

    it('renders empty content without errors', () => {
        const { container } = render(<LemonTipTap>{''}</LemonTipTap>)

        expect(container.querySelector('.LemonTipTap')).toBeInTheDocument()
    })

    it('applies custom className', () => {
        const { container } = render(<LemonTipTap className="custom-class">Test</LemonTipTap>)

        expect(container.querySelector('.LemonTipTap.custom-class')).toBeInTheDocument()
    })
})
