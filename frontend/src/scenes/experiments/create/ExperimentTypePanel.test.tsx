import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { NEW_EXPERIMENT } from '../constants'
import { ExperimentTypePanel } from './ExperimentTypePanel'

describe('ExperimentTypePanel', () => {
    const mockSetExperimentType = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    describe('rendering', () => {
        it('renders both experiment type options', () => {
            const { container } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            expect(screen.getByText('Product experiment')).toBeInTheDocument()
            expect(screen.getByText('Use custom code to manage how variants modify your product.')).toBeInTheDocument()

            expect(screen.getByText(/No-Code experiment/)).toBeInTheDocument()
            expect(
                screen.getByText('Define variants on your website using the PostHog toolbar, no coding required.')
            ).toBeInTheDocument()

            const cards = container.querySelectorAll('[role="button"]')
            expect(cards).toHaveLength(2)
        })

        it('shows Beta tag on no-code experiment option', () => {
            render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            expect(screen.getByText('Beta')).toBeInTheDocument()
        })

        it('highlights selected option with check icon', () => {
            const { container, rerender } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const productCard = cards[0]
            const noCodeCard = cards[1]

            expect(productCard).toHaveClass('border-accent')
            expect(productCard).toHaveAttribute('aria-pressed', 'true')

            expect(noCodeCard).not.toHaveClass('border-accent')
            expect(noCodeCard).toHaveAttribute('aria-pressed', 'false')

            rerender(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'web' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const updatedCards = container.querySelectorAll('[role="button"]')
            const updatedProductCard = updatedCards[0]
            const updatedNoCodeCard = updatedCards[1]

            expect(updatedProductCard).not.toHaveClass('border-accent')
            expect(updatedProductCard).toHaveAttribute('aria-pressed', 'false')

            expect(updatedNoCodeCard).toHaveClass('border-accent')
            expect(updatedNoCodeCard).toHaveAttribute('aria-pressed', 'true')
        })
    })

    describe('interactions', () => {
        it('calls setExperimentType with "product" when clicking product card', async () => {
            const { container } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'web' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const productCard = cards[0]
            userEvent.click(productCard)

            expect(mockSetExperimentType).toHaveBeenCalledWith('product')
            expect(mockSetExperimentType).toHaveBeenCalledTimes(1)
        })

        it('calls setExperimentType with "web" when clicking no-code card', async () => {
            const { container } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const noCodeCard = cards[1]
            userEvent.click(noCodeCard)

            expect(mockSetExperimentType).toHaveBeenCalledWith('web')
            expect(mockSetExperimentType).toHaveBeenCalledTimes(1)
        })

        it('supports keyboard navigation with Enter key', async () => {
            const { container } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const noCodeCard = cards[1] as HTMLElement
            noCodeCard.focus()
            userEvent.keyboard('{Enter}')

            expect(mockSetExperimentType).toHaveBeenCalledWith('web')
        })

        it('supports keyboard navigation with Space key', async () => {
            const { container } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const noCodeCard = cards[1] as HTMLElement
            noCodeCard.focus()
            userEvent.keyboard(' ')

            expect(mockSetExperimentType).toHaveBeenCalledWith('web')
        })

        it('calls setExperimentType even when clicking already selected option', async () => {
            const { container } = render(
                <ExperimentTypePanel
                    experiment={{ ...NEW_EXPERIMENT, type: 'product' }}
                    setExperimentType={mockSetExperimentType}
                />
            )

            const cards = container.querySelectorAll('[role="button"]')
            const productCard = cards[0]
            userEvent.click(productCard)

            expect(mockSetExperimentType).toHaveBeenCalledWith('product')
        })
    })
})
