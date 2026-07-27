import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { AIObservabilityEventCard } from './AIObservabilityEventCard'

describe('AIObservabilityEventCard', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    const renderCard = (event: { event: string; properties: Record<string, unknown> }): HTMLElement => {
        const { container } = render(
            <Provider>
                <AIObservabilityEventCard
                    event={{ id: 'event-1', createdAt: '2024-01-01T00:00:00Z', ...event }}
                    isExpanded={false}
                    onToggleExpand={() => {}}
                />
            </Provider>
        )
        return container
    }

    it('renders a string model for a generation', () => {
        renderCard({ event: '$ai_generation', properties: { $ai_model: 'gpt-4o' } })
        expect(screen.getByText('gpt-4o')).toBeInTheDocument()
    })

    it('renders a string span name for a span', () => {
        renderCard({ event: '$ai_span', properties: { $ai_span_name: 'My Span' } })
        expect(screen.getByText('My Span')).toBeInTheDocument()
    })

    // A non-string `$ai_model`/`$ai_span_name` (the property bag is untyped) must not be rendered
    // verbatim, or React throws error #31 ("Objects are not valid as a React child").
    const nonStringCases: [string, string, Record<string, unknown>, string][] = [
        ['generation with object model', '$ai_generation', { $ai_model: {} }, 'Unknown model'],
        ['generation with array model', '$ai_generation', { $ai_model: [] }, 'Unknown model'],
        ['embedding with object model', '$ai_embedding', { $ai_model: {} }, 'Unknown model'],
        ['span with object span name', '$ai_span', { $ai_span_name: {} }, 'Unnamed span'],
    ]

    it.each(nonStringCases)('renders %s without throwing', (_label, event, properties, expectedFallback) => {
        renderCard({ event, properties })
        expect(screen.getByText(expectedFallback)).toBeInTheDocument()
    })
})
