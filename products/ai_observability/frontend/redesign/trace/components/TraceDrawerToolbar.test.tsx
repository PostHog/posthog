import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { TraceDrawerToolbar, TraceDrawerToolbarProps } from './TraceDrawerToolbar'

const props: TraceDrawerToolbarProps = {
    position: { index: 0, total: 3 },
    onPrevious: null,
    onNext: null,
    fullPageHref: '/traces/a',
    onClose: () => {},
}

describe('TraceDrawerToolbar back button', () => {
    afterEach(cleanup)

    it('renders nothing without back', () => {
        const { container } = render(<TraceDrawerToolbar {...props} />)
        expect(container.querySelector('[data-attr="trace-drawer-back"]')).toBeNull()
    })

    it('renders the label masked and calls onBack', () => {
        const onBack = jest.fn()
        const { getByText } = render(<TraceDrawerToolbar {...props} back={{ label: 'Back to errors', onBack }} />)
        const label = getByText('Back to errors')
        expect(label).toHaveClass('ph-sensitive', 'ph-mask')
        fireEvent.click(label)
        expect(onBack).toHaveBeenCalledTimes(1)
    })
})
