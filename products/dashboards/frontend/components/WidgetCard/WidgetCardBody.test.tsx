import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { WidgetCardBody } from './WidgetCardBody'

describe('WidgetCardBody', () => {
    it('renders children', () => {
        render(
            <WidgetCardBody>
                <div>Loaded content</div>
            </WidgetCardBody>
        )

        expect(screen.getByText('Loaded content')).toBeInTheDocument()
    })

    it('renders locked message with lock icon instead of children', () => {
        const { container } = render(
            <WidgetCardBody locked>
                <div>Hidden content</div>
            </WidgetCardBody>
        )

        expect(screen.getByText('You do not have access to view this widget.')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="widget-card-body-locked"] svg')).toBeInTheDocument()
        expect(screen.queryByText('Hidden content')).not.toBeInTheDocument()
    })

    it('renders error message instead of children', () => {
        render(
            <WidgetCardBody error="Something went wrong">
                <div>Hidden content</div>
            </WidgetCardBody>
        )

        expect(screen.getByText('Something went wrong')).toBeInTheDocument()
        expect(screen.queryByText('Hidden content')).not.toBeInTheDocument()
    })

    it('renders refresh button on error when onRefresh is provided', async () => {
        const onRefresh = jest.fn()
        render(
            <WidgetCardBody error="Something went wrong" onRefresh={onRefresh}>
                <div>Hidden content</div>
            </WidgetCardBody>
        )

        const refreshButton = screen.getByRole('button', { name: 'Refresh data' })
        expect(refreshButton).toBeInTheDocument()
        refreshButton.click()
        expect(onRefresh).toHaveBeenCalledTimes(1)
    })

    it('centers locked message in the body', () => {
        const { container } = render(
            <WidgetCardBody locked>
                <div>Hidden content</div>
            </WidgetCardBody>
        )

        const messageContainer = container.querySelector('[data-slot="widget-card-body-message"]')
        expect(messageContainer).toHaveClass('flex', 'min-h-full', 'items-center', 'justify-center', 'text-center')
    })

    it('declares a widget-card container for body layout queries', () => {
        const { container } = render(
            <WidgetCardBody>
                <div>Loaded content</div>
            </WidgetCardBody>
        )

        expect(container.firstChild).toHaveClass('@container/widget-card')
    })

    it('centers error message in the body', () => {
        const { container } = render(
            <WidgetCardBody error="Something went wrong">
                <div>Hidden content</div>
            </WidgetCardBody>
        )

        const messageContainer = container.querySelector('[data-slot="widget-card-body-message"]')
        expect(messageContainer).toHaveClass('flex', 'min-h-full', 'items-center', 'justify-center', 'text-center')
    })
})
