import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'

import { DataSourceIcon } from './DataSourceIcon'

// Mocking because it is annoying to mock the hover to assert the tooltip text
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    Tooltip: ({ children, title }: { children: React.ReactNode; title: string }) => (
        <div data-attr={title}>{children}</div>
    ),
}))

describe('DataSourceIcon', () => {
    afterEach(() => {
        cleanup()
    })

    it('should render piggybank icon for revenue-analytics source', async () => {
        render(<DataSourceIcon source="revenue-analytics" />)

        expect(screen.getByTestId('piggybank-icon')).toHaveClass('w-3 h-3 text-muted')
        expect(screen.getByTestId('piggybank-icon')).toBeInTheDocument()
        expect(screen.getByTestId('From Revenue analytics')).toBeInTheDocument()
    })

    it('should render database icon for properties source', () => {
        render(<DataSourceIcon source="properties" />)

        expect(screen.getByTestId('database-icon')).toBeInTheDocument()
        expect(screen.getByTestId('database-icon')).toHaveClass('w-3 h-3 text-muted')
        expect(screen.getByTestId('From group properties')).toBeInTheDocument()
    })

    it('should render nothing for null source', () => {
        const { container } = render(<DataSourceIcon source={null} />)

        expect(container.firstChild).toBeNull()
    })
})
