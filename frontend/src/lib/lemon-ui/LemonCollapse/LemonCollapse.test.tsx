import '@testing-library/jest-dom'

import { render, within } from '@testing-library/react'

import { LemonCollapse } from './LemonCollapse'

describe('LemonCollapse', () => {
    const panels = [{ key: 'only', header: 'Header', content: <div>Body</div> }]

    // A collapsed panel unmounts its content, so a caller that drives the panel from outside needs
    // "closed" to hold. Reading `activeKey` by value instead of by presence loses that, because the
    // panel then falls back on whatever the person last clicked.
    it('honors a controlled close over the internal state', () => {
        const { container } = render(<LemonCollapse panels={panels} defaultActiveKey="only" activeKey={null} />)

        expect(within(container).queryByText('Body')).not.toBeInTheDocument()
    })

    it('still seeds itself from defaultActiveKey when left uncontrolled', () => {
        const { container } = render(<LemonCollapse panels={panels} defaultActiveKey="only" />)

        expect(within(container).getByText('Body')).toBeInTheDocument()
    })

    // The header button is the only focusable control, so a screen reader can only learn that the
    // panel hides content, and what it hides, from the button itself.
    it('states the panel state and the body it controls on the header button', () => {
        const { container, rerender } = render(<LemonCollapse panels={panels} />)
        const header = (): HTMLElement => container.querySelector<HTMLElement>('.LemonCollapsePanel__header')!

        expect(header()).toHaveAttribute('aria-expanded', 'false')
        expect(header()).not.toHaveAttribute('aria-controls')

        rerender(<LemonCollapse panels={panels} activeKey="only" />)

        expect(header()).toHaveAttribute('aria-expanded', 'true')
        const body = within(container).getByText('Body').closest('.LemonCollapsePanel__body')
        expect(body?.id).toBeTruthy()
        expect(header()).toHaveAttribute('aria-controls', body?.id)
    })
})
