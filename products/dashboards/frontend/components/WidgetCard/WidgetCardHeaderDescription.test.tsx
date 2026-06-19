import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { WidgetCardHeaderDescription } from './WidgetCardHeader'

describe('WidgetCardHeaderDescription', () => {
    it('renders markdown when description is set and visible', () => {
        render(<WidgetCardHeaderDescription description="Weekly error summary" showDescription />)

        expect(screen.getByText('Weekly error summary')).toBeInTheDocument()
    })

    it('does not render when description is empty', () => {
        const { container } = render(<WidgetCardHeaderDescription description="" showDescription />)

        expect(container.querySelector('[data-slot="widget-card-header-description"]')).toBeNull()
    })

    it('does not render when description visibility is off', () => {
        const { container } = render(
            <WidgetCardHeaderDescription description="Hidden description" showDescription={false} />
        )

        expect(container.querySelector('[data-slot="widget-card-header-description"]')).toBeNull()
    })
})
