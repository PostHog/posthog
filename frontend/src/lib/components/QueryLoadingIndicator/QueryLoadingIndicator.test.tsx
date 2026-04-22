import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { QueryLoadingIndicator } from './QueryLoadingIndicator'

describe('QueryLoadingIndicator', () => {
    afterEach(() => {
        cleanup()
    })

    describe('Initial load (no cached results)', () => {
        it('renders full loading state with message', () => {
            render(<QueryLoadingIndicator queryId="test-123" hasCachedResults={false} height={300} />)

            expect(screen.getByText(/insights/i)).toBeInTheDocument()
            expect(screen.getByText('test-123')).toBeInTheDocument()
        })

        it('shows loading details when showDetails is true', () => {
            render(<QueryLoadingIndicator queryId="test-details" hasCachedResults={false} showDetails={true} />)

            // Should show query ID when showDetails is true
            expect(screen.getByText('test-details')).toBeInTheDocument()
            expect(screen.getByText(/Query ID:/)).toBeInTheDocument()
        })

        it('hides loading details when showDetails is false', () => {
            const pollResponse = {
                status: {
                    query_progress: {
                        rows_read: 1000000,
                        bytes_read: 52428800,
                    },
                    start_time: new Date().toISOString(),
                },
            }

            render(
                <QueryLoadingIndicator
                    queryId="test-no-details"
                    hasCachedResults={false}
                    showDetails={false}
                    pollResponse={pollResponse}
                />
            )

            // Should not show query ID or rows
            expect(screen.queryByText('test-no-details')).not.toBeInTheDocument()
            expect(screen.queryByText(/rows/)).not.toBeInTheDocument()
        })

        it('displays custom suggestion when provided', () => {
            const customSuggestion = <div>Try filtering by date range</div>

            render(
                <QueryLoadingIndicator queryId="test-custom" hasCachedResults={false} suggestion={customSuggestion} />
            )

            expect(screen.getByText('Try filtering by date range')).toBeInTheDocument()
        })
    })

    describe('Cached results refresh', () => {
        it('shows only loading bar when results are cached', () => {
            render(<QueryLoadingIndicator queryId="test-cached" hasCachedResults={true} height={80} />)

            // Should not show loading message or details
            expect(screen.queryByText(/insights/i)).not.toBeInTheDocument()
            expect(screen.queryByText(/Query ID:/)).not.toBeInTheDocument()
        })

        it('respects height prop for cached results', () => {
            const { container } = render(
                <QueryLoadingIndicator queryId="test-height" hasCachedResults={true} height={60} />
            )

            const wrapper = container.firstChild as HTMLElement
            expect(wrapper.style.height).toBe('60px')
        })
    })

    describe('Height prop', () => {
        it('applies height style when provided', () => {
            const { container } = render(<QueryLoadingIndicator queryId="test" hasCachedResults={false} height={250} />)

            const loadingDiv = container.querySelector('[data-attr="query-loading-indicator"]') as HTMLElement
            expect(loadingDiv.style.height).toBe('250px')
        })

        it('does not apply height style when not provided', () => {
            const { container } = render(<QueryLoadingIndicator queryId="test" hasCachedResults={false} />)

            const loadingDiv = container.querySelector('[data-attr="query-loading-indicator"]') as HTMLElement
            expect(loadingDiv.style.height).toBe('')
        })
    })
})
