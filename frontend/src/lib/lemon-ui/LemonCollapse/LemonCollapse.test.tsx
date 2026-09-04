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
})
