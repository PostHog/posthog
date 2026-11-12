import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { ToolCallPart } from './ToolCallPart'

describe('ToolCallPart', () => {
    it('renders a call the server reports without a result as a bare call', () => {
        const { container } = render(<ToolCallPart name="lookup" args={{ id: 1 }} result={null} />)

        expect(container).toHaveTextContent('lookup')
        expect(container).not.toHaveTextContent('Result')
    })

    it('renders the result of a call that has one', () => {
        const { container } = render(<ToolCallPart name="lookup" args={{}} result="ok" />)

        expect(container).toHaveTextContent('Result')
    })
})
