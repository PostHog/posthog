import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { AnalyticsMetricCard } from './AnalyticsMetricCard'

describe('AnalyticsMetricCard', () => {
    afterEach(cleanup)
    it('keeps static metrics out of the keyboard tab order', () => {
        render(<AnalyticsMetricCard title="Sessions" value={120} />)
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
        expect(screen.getByText('Sessions')).toBeInTheDocument()
    })

    it('supports keyboard selection with native button behavior', async () => {
        const onClick = jest.fn()
        render(<AnalyticsMetricCard title="Sessions" value={120} onClick={onClick} selected={false} />)
        await userEvent.tab()
        expect(screen.getByRole('button')).toHaveFocus()
        await userEvent.keyboard('{Enter}')
        await userEvent.keyboard(' ')
        expect(onClick).toHaveBeenCalledTimes(2)
        expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false')
    })

    it('does not trigger a containing click action', () => {
        const parentClick = jest.fn()
        const onClick = jest.fn()
        render(
            <div onClick={parentClick}>
                <AnalyticsMetricCard title="Sessions" value={120} onClick={onClick} selected />
            </div>
        )
        fireEvent.click(screen.getByRole('button'))
        expect(onClick).toHaveBeenCalledTimes(1)
        expect(parentClick).not.toHaveBeenCalled()
        expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
    })

    it('keeps loading distinct from an empty or failed response', () => {
        const { rerender } = render(<AnalyticsMetricCard title="Sessions" loading error="Could not load" />)
        expect(screen.queryByText('Could not load')).not.toBeInTheDocument()
        expect(screen.queryByText('No data for this period')).not.toBeInTheDocument()
        rerender(<AnalyticsMetricCard title="Sessions" error="Could not load" />)
        expect(screen.getByText('Could not load')).toBeInTheDocument()
        rerender(<AnalyticsMetricCard title="Sessions" />)
        expect(screen.getByText('No data for this period')).toBeInTheDocument()
    })
})
