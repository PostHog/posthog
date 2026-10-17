import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { TodayPulseMovers } from './TodayPulseMovers'

describe('TodayPulseMovers', () => {
    afterEach(() => cleanup())

    it('shows a negative series value as it is instead of a bar floored at zero', () => {
        render(
            <TodayPulseMovers
                movers={[
                    { label: 'Refunds', value: -50, change_pct: -20 },
                    { label: 'Orders', value: 120, change_pct: 10 },
                ]}
                formatValue={(value) => `v${value}`}
            />
        )

        expect(screen.getByText('v-50')).toBeInTheDocument()
        expect(screen.getByText('v120')).toBeInTheDocument()
    })
})
